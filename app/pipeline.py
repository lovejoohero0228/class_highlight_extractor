from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.clipper import normalize_blocks
from app.config import settings
from app.ffmpeg_utils import create_clip, extract_audio, probe_video
from app.highlight_detection import (
    generate_rule_candidates,
    refine_candidates_with_gpt,
    transcript_excerpt_for_range,
)
from app.models import CandidateReview, Clip, JobStatus, TranscriptSegment
from app.storage import (
    audio_path_for,
    clip_output_path,
    find_cached_transcript_source_by_filename,
    get_job,
    save_job,
    transcript_path_for,
)
from app.transcription import transcribe_audio


def _apply_clip_shape(clips: list[Clip], duration: float, clip_shape: str) -> list[Clip]:
    buffer_sec = 0
    if clip_shape == "buffer_3s":
        buffer_sec = 3
    elif clip_shape == "buffer_5s":
        buffer_sec = 5
    if buffer_sec == 0:
        return clips

    adjusted: list[Clip] = []
    for clip in clips:
        start = max(0.0, clip.clip_start - buffer_sec)
        end = min(duration, clip.clip_end + buffer_sec)
        if end - start < settings.min_clip_sec:
            end = min(duration, start + settings.min_clip_sec)
        if end - start > settings.max_clip_sec:
            end = start + settings.max_clip_sec
        adjusted.append(
            clip.model_copy(
                update={
                    "clip_start": round(start, 3),
                    "clip_end": round(end, 3),
                    "clip_duration": round(end - start, 3),
                }
            )
        )
    return adjusted


def _activity_label(activity_type: str) -> str:
    mapping = {
        "answering": "질문-응답 참여",
        "repeating": "따라 말하기 참여",
        "singing": "노래/챈트 참여",
        "playing": "활동형 참여",
        "unknown": "일반 참여",
    }
    return mapping.get(activity_type, activity_type)


def _clean_utterance(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned.strip('"“”')


def _collect_clip_quotes(
    clip: Clip,
    segments: list[TranscriptSegment],
    max_quotes: int = 4,
) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        overlaps = segment.end_time >= clip.clip_start and segment.start_time <= clip.clip_end
        if not overlaps:
            continue
        utterance = _clean_utterance(segment.text)
        if len(utterance) < 4:
            continue
        key = utterance.lower()
        if key in seen:
            continue
        seen.add(key)
        quotes.append(utterance)
        if len(quotes) >= max_quotes:
            break
    return quotes


def _build_clip_explanation(
    clip: Clip,
    all_candidates: list[CandidateReview],
    custom_prompt: str,
    segments: list[TranscriptSegment],
) -> str:
    main = _activity_label(clip.activity_type)
    quotes = _collect_clip_quotes(clip, segments, max_quotes=4)
    lines: list[str] = []

    lines.append(f"이 장면은 '{main}' 흐름이 선명하게 드러나는 구간입니다.")

    if quotes:
        quoted = ", ".join([f"\"{quote}\"" for quote in quotes[:3]])
        lines.append(f"핵심 발화는 {quoted} 등으로 확인됩니다.")
    else:
        lines.append("대사 흐름상 교사 유도와 아동 참여가 연속적으로 이어지는 구조가 확인됩니다.")

    if clip.activity_type == "answering":
        lines.append("교사 발문 이후 아동이 반응하고, 교사의 후속 멘트가 이어져 질문-응답 사이클이 완결됩니다.")
    elif clip.activity_type == "repeating":
        lines.append("교사의 모델 발화를 아동이 반복하는 패턴이 유지되어, 발화 훈련 장면으로 해석됩니다.")
    elif clip.activity_type == "singing":
        lines.append("리듬성 있는 반복 발화가 이어져 노래/챈트 중심 활동 장면으로 분류됩니다.")
    else:
        lines.append("참여 발화가 끊기지 않고 연결되어 수업 상호작용이 분명한 장면입니다.")

    lines.append("수업 흐름이 끊기지 않고 참여 반응이 자연스럽게 이어져 하이라이트로 선정되었습니다.")

    if custom_prompt:
        lines.append(f"사용자 요청 반영 포인트: {custom_prompt[:160]}")

    return "\n".join(lines)


def process_video(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    try:
        job.status = JobStatus.processing
        job.progress = 5
        job.message = "영상 메타데이터를 확인하고 있습니다."
        save_job(job)

        metadata = probe_video(Path(job.video.source_path))
        job.video.duration_seconds = float(metadata["duration_seconds"])
        job.video.orientation = str(metadata["orientation"])
        job.progress = 15
        job.message = "오디오를 추출하고 있습니다."
        save_job(job)

        audio_path = audio_path_for(job.job_id)
        extract_audio(Path(job.video.source_path), audio_path)

        job.progress = 35
        job.message = "음성을 텍스트로 변환하고 있습니다."
        save_job(job)

        transcript_path = transcript_path_for(job.job_id)
        cached_transcript = find_cached_transcript_source_by_filename(
            job.video.original_filename,
            exclude_job_id=job.job_id,
        )
        if cached_transcript and not transcript_path.exists():
            shutil.copyfile(cached_transcript, transcript_path)
            job.message = "기존 동일 파일명의 transcript를 재사용했습니다."
            save_job(job)
        segments = transcribe_audio(audio_path, transcript_path)
        job.transcript_path = str(transcript_path.resolve())

        job.progress = 60
        job.message = "후보 하이라이트를 찾고 있습니다."
        save_job(job)

        duration = job.video.duration_seconds or 0.0
        candidates = generate_rule_candidates(segments, duration)
        refined_blocks = refine_candidates_with_gpt(segments, candidates, duration, job.options)
        for block in refined_blocks:
            block.transcript_excerpt = transcript_excerpt_for_range(
                segments,
                block.start_time,
                block.end_time,
            )
        clips = normalize_blocks(refined_blocks, duration, job.video.video_id)
        clips = _apply_clip_shape(clips, duration, job.options.clip_shape)

        job.progress = 80
        job.message = "클립을 렌더링하고 있습니다."
        save_job(job)

        rendered_clips = []
        for index, clip in enumerate(clips, start=1):
            output_path = clip_output_path(job.job_id, index)
            create_clip(Path(job.video.source_path), output_path, clip.clip_start, clip.clip_end)
            clip.output_path = str(output_path.resolve())
            clip.preview_url = f"/api/clips/{clip.clip_id}/preview"
            clip.download_url = f"/api/clips/{clip.clip_id}/download"
            rendered_clips.append(clip)

        selected_candidate_ids = {clip.source_candidate_id for clip in rendered_clips if clip.source_candidate_id}
        candidate_reviews = [
            CandidateReview(
                candidate_id=block.candidate_id or f"cand_{index}",
                start_time=round(block.start_time, 3),
                end_time=round(block.end_time, 3),
                activity_type=block.activity_type,
                confidence_score=round(block.confidence_score, 3),
                reason=block.reason,
                transcript_excerpt=block.transcript_excerpt,
                selected=(block.candidate_id in selected_candidate_ids),
            )
            for index, block in enumerate(refined_blocks, start=1)
        ]
        job.candidate_reviews = candidate_reviews

        for clip in rendered_clips:
            clip.explain_text = _build_clip_explanation(
                clip,
                candidate_reviews,
                job.options.custom_prompt,
                segments,
            )

        job.clips = rendered_clips
        job.status = JobStatus.completed
        job.progress = 100
        job.message = f"완료되었습니다. 클립 {len(rendered_clips)}개를 생성했습니다."
        save_job(job)
    except Exception as exc:  # noqa: BLE001
        job.status = JobStatus.failed
        job.progress = 100
        job.error = str(exc)
        job.message = "처리에 실패했습니다."
        save_job(job)
