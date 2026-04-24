from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import UploadFile
from pydantic import ValidationError

from app.config import settings
from app.models import CandidateReview, Clip, ExtractionOptions, Job, JobStatus, TranscriptSegment, VideoMetadata


def _job_path(job_id: str) -> Path:
    return settings.jobs_dir / f"{job_id}.json"


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "upload.mp4").strip("._")
    return cleaned or "upload.mp4"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as temp_file:
        temp_file.write(serialized)
        temp_path = Path(temp_file.name)
    temp_path.replace(path)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_transcript_segments(job: Job) -> list[TranscriptSegment]:
    if not job.transcript_path:
        return []
    transcript_path = Path(job.transcript_path)
    if not transcript_path.exists():
        return []
    try:
        payload = load_json(transcript_path)
    except (OSError, json.JSONDecodeError):
        return []
    return [TranscriptSegment.model_validate(item) for item in payload]


def _excerpt_for_range(segments: list[TranscriptSegment], start_time: float, end_time: float, limit: int = 8) -> str:
    matched: list[str] = []
    for segment in segments:
        overlaps = segment.end_time >= start_time and segment.start_time <= end_time
        if not overlaps:
            continue
        matched.append(f"[{segment.start_time:.1f}-{segment.end_time:.1f}] {segment.text}")
        if len(matched) >= limit:
            break
    return "\n".join(matched)


def _legacy_explain_from_excerpt(excerpt: str) -> str:
    lines = [line.strip() for line in excerpt.splitlines() if line.strip()]
    quotes: list[str] = []
    seen: set[str] = set()
    for line in lines:
        utterance = re.sub(r"^\[[^\]]+\]\s*", "", line).strip()
        utterance = re.sub(r"\s+", " ", utterance).strip('"“”')
        if len(utterance) < 4:
            continue
        key = utterance.lower()
        if key in seen:
            continue
        seen.add(key)
        quotes.append(utterance)
        if len(quotes) >= 3:
            break

    if quotes:
        return (
            "이 장면은 수업 상호작용이 연속적으로 이어지는 참여 구간입니다.\n"
            f"핵심 발화는 {', '.join([f'\"{item}\"' for item in quotes])} 등으로 확인됩니다.\n"
            "교사 유도와 아동 반응이 자연스럽게 연결되어 하이라이트로 선정되었습니다."
        )
    return (
        "이 장면은 교사 유도와 아동 반응이 연속적으로 이어진 참여 구간입니다.\n"
        "발화 흐름의 완결성이 높아 하이라이트로 선정되었습니다."
    )


def _default_message(job: Job) -> str:
    if job.status == JobStatus.uploaded:
        return "업로드가 완료되었습니다. 처리를 기다리는 중입니다."
    if job.status == JobStatus.processing:
        return "영상을 처리하고 있습니다."
    if job.status == JobStatus.completed:
        return f"완료되었습니다. 클립 {len(job.clips)}개를 생성했습니다."
    if job.status == JobStatus.failed:
        return "처리에 실패했습니다."
    return job.message


def hydrate_job(job: Job) -> Job:
    changed = False
    job_path = _job_path(job.job_id)
    stat = job_path.stat() if job_path.exists() else None
    transcript_segments = _load_transcript_segments(job)

    if not job.created_at and stat:
        job.created_at = datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
        changed = True
    if not job.updated_at and stat:
        job.updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        changed = True
    if not job.request_group_id:
        job.request_group_id = f"legacy_{job.job_id}"
        changed = True
    if not job.request_label:
        job.request_label = "이전 저장 결과"
        changed = True
    if not job.options:
        job.options = ExtractionOptions()
        changed = True
    if (
        not job.message
        or job.message.startswith("Upload complete")
        or job.message.startswith("Completed.")
        or job.message == "Processing failed."
    ):
        job.message = _default_message(job)
        changed = True

    for clip in job.clips:
        preview_url = f"/api/clips/{clip.clip_id}/preview"
        download_url = f"/api/clips/{clip.clip_id}/download"
        if clip.preview_url != preview_url:
            clip.preview_url = preview_url
            changed = True
        if clip.download_url != download_url:
            clip.download_url = download_url
            changed = True
        if not clip.explain_text:
            clip.explain_text = "이 클립은 참여 가능성이 높은 구간으로 자동 선정되었습니다."
            changed = True
        if ("신뢰도는" in clip.explain_text) or re.search(r"\[[0-9.]+\s*-\s*[0-9.]+\]", clip.explain_text):
            clip.explain_text = _legacy_explain_from_excerpt(clip.transcript_excerpt)
            changed = True
        if not clip.transcript_excerpt and transcript_segments:
            clip.transcript_excerpt = _excerpt_for_range(transcript_segments, clip.clip_start, clip.clip_end)
            changed = True
        if not clip.source_candidate_id:
            clip.source_candidate_id = f"legacy_{clip.clip_id}"
            changed = True

    if not job.candidate_reviews and job.clips:
        job.candidate_reviews = [
            CandidateReview(
                candidate_id=clip.source_candidate_id or f"legacy_{clip.clip_id}",
                start_time=clip.clip_start,
                end_time=clip.clip_end,
                activity_type=clip.activity_type,
                confidence_score=clip.confidence_score,
                reason=clip.explain_text or "기존 결과에서 복원된 후보입니다.",
                transcript_excerpt=clip.transcript_excerpt,
                selected=True,
            )
            for clip in job.clips
        ]
        changed = True

    if changed:
        save_job(job)
    return job


async def create_job(
    file: UploadFile,
    request_group_id: str = "",
    request_label: str = "",
    options: ExtractionOptions | None = None,
) -> Job:
    job_id = f"job_{uuid4().hex[:12]}"
    video_id = f"video_{uuid4().hex[:12]}"
    safe_filename = _safe_filename(file.filename or "upload.mp4")
    upload_path = settings.uploads_dir / f"{job_id}_{safe_filename}"
    now = _now_iso()

    async with aiofiles.open(upload_path, "wb") as out_file:
        while chunk := await file.read(1024 * 1024):
            await out_file.write(chunk)

    job = Job(
        job_id=job_id,
        request_group_id=request_group_id or f"request_{uuid4().hex[:10]}",
        request_label=request_label or "새 업로드",
        created_at=now,
        updated_at=now,
        status=JobStatus.uploaded,
        progress=0,
        message="업로드가 완료되었습니다. 처리를 기다리는 중입니다.",
        options=options or ExtractionOptions(),
        video=VideoMetadata(
            video_id=video_id,
            original_filename=file.filename or safe_filename,
            source_path=str(upload_path.resolve()),
        ),
    )
    save_job(job)
    return job


def save_job(job: Job) -> None:
    if not job.created_at:
        job.created_at = _now_iso()
    job.updated_at = _now_iso()
    save_json(_job_path(job.job_id), job.model_dump(mode="json"))


def get_job(job_id: str) -> Job | None:
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        return hydrate_job(Job.model_validate(load_json(path)))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def list_jobs() -> list[Job]:
    jobs: list[Job] = []
    for path in sorted(settings.jobs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            jobs.append(hydrate_job(Job.model_validate(load_json(path))))
        except (OSError, json.JSONDecodeError, ValidationError):
            continue
    return jobs


def transcript_path_for(job_id: str) -> Path:
    return settings.transcripts_dir / f"{job_id}.json"


def audio_path_for(job_id: str) -> Path:
    return settings.audio_dir / f"{job_id}.wav"


def clip_output_dir(job_id: str) -> Path:
    return settings.clips_dir / job_id


def clip_output_path(job_id: str, index: int) -> Path:
    return clip_output_dir(job_id) / f"clip_{index:03d}.mp4"


def find_cached_transcript_source_by_filename(original_filename: str, exclude_job_id: str = "") -> Path | None:
    target = (original_filename or "").strip().lower()
    if not target:
        return None

    for job in list_jobs():
        if exclude_job_id and job.job_id == exclude_job_id:
            continue
        if (job.video.original_filename or "").strip().lower() != target:
            continue
        if not job.transcript_path:
            continue
        transcript_path = Path(job.transcript_path)
        if transcript_path.exists():
            return transcript_path
    return None


def find_clip(clip_id: str) -> tuple[Clip | None, Job | None]:
    for job in list_jobs():
        for clip in job.clips:
            if clip.clip_id == clip_id:
                return clip, job
    return None, None
