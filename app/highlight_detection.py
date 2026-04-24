from __future__ import annotations

import json
import re
from typing import Iterable
from uuid import uuid4

from openai import OpenAI

from app.config import settings
from app.models import ActivityBlock, ExtractionOptions, TranscriptSegment

QUESTION_PATTERNS = [
    r"\bwhat is this\b",
    r"\bwhat color\b",
    r"\bwhat animal\b",
    r"\bhow many\b",
    r"\bwho is this\b",
    r"\bcan you say\b",
    r"\brepeat after me\b",
    r"\bsay it again\b",
    r"\bwhat do you see\b",
    r"\bis it a\b",
    r"\bdo you like\b",
    r"\blet'?s say\b",
    r"\blet'?s read\b",
]
REPEAT_PATTERNS = [
    r"\brepeat after me\b",
    r"\bsay\b",
    r"\bone more time\b",
    r"\btogether\b",
    r"\beverybody\b",
    r"\bagain\b",
]
SING_PATTERNS = [
    r"\bsong\b",
    r"\bsing\b",
    r"\bmusic\b",
    r"\bclap\b",
    r"\bchant\b",
    r"\blet'?s sing\b",
]
PRAISE_PATTERNS = [
    r"\bgood job\b",
    r"\bgreat\b",
    r"\bexcellent\b",
    r"\bvery good\b",
    r"\bwell done\b",
    r"\bnice\b",
]


def _matches(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _normalize_reason(reason: str) -> str:
    parts = [part.strip() for part in re.split(r"[.]\s+", reason.strip()) if part.strip()]
    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        key = part.lower().rstrip(".")
        if key in seen:
            continue
        seen.add(key)
        unique_parts.append(part.rstrip("."))
    if not unique_parts:
        return ""
    return ". ".join(unique_parts) + "."


def _candidate(
    start_time: float,
    end_time: float,
    activity_type: str,
    confidence_score: float,
    reason: str,
) -> ActivityBlock:
    return ActivityBlock(
        candidate_id=f"cand_{uuid4().hex[:10]}",
        start_time=start_time,
        end_time=end_time,
        activity_type=activity_type,
        confidence_score=confidence_score,
        reason=reason,
    )


def transcript_excerpt_for_range(
    segments: list[TranscriptSegment],
    start_time: float,
    end_time: float,
    limit: int = 8,
) -> str:
    lines: list[str] = []
    for segment in segments:
        overlaps = segment.end_time >= start_time and segment.start_time <= end_time
        if not overlaps:
            continue
        lines.append(f"[{segment.start_time:.1f}-{segment.end_time:.1f}] {segment.text}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def generate_rule_candidates(segments: list[TranscriptSegment], video_duration_sec: float) -> list[ActivityBlock]:
    candidates: list[ActivityBlock] = []
    for segment in segments:
        text = segment.text.lower()
        if _matches(QUESTION_PATTERNS, text):
            candidates.append(
                _candidate(
                    start_time=segment.start_time,
                    end_time=min(video_duration_sec, max(segment.end_time + 15, segment.start_time + 5)),
                    activity_type="answering",
                    confidence_score=0.72,
                    reason="교사 발문 뒤에 아동 반응이 이어진 참여 구간입니다.",
                )
            )
        if _matches(REPEAT_PATTERNS, text):
            candidates.append(
                _candidate(
                    start_time=segment.start_time,
                    end_time=min(video_duration_sec, max(segment.end_time + 25, segment.start_time + 10)),
                    activity_type="repeating",
                    confidence_score=0.68,
                    reason="따라 말하기 활동 신호가 감지되었습니다.",
                )
            )
        if _matches(SING_PATTERNS, text):
            candidates.append(
                _candidate(
                    start_time=segment.start_time,
                    end_time=min(video_duration_sec, max(segment.end_time + 60, segment.start_time + 30)),
                    activity_type="singing",
                    confidence_score=0.7,
                    reason="노래 또는 챈트 활동 신호가 감지되었습니다.",
                )
            )
        if _matches(PRAISE_PATTERNS, text):
            start_time = max(0.0, segment.start_time - 20)
            candidates.append(
                _candidate(
                    start_time=start_time,
                    end_time=min(video_duration_sec, segment.end_time + 15),
                    activity_type="answering",
                    confidence_score=0.62,
                    reason="교사의 긍정 피드백이 관찰된 참여 구간입니다.",
                )
            )

    return merge_candidates(candidates, video_duration_sec)


def apply_focus_mode(candidates: list[ActivityBlock], focus_mode: str) -> list[ActivityBlock]:
    if focus_mode == "balanced":
        return candidates

    weighted: list[ActivityBlock] = []
    for item in candidates:
        delta = 0.0
        if focus_mode == "kids_talk":
            if item.activity_type in {"answering", "repeating"}:
                delta = 0.08
            elif item.activity_type == "singing":
                delta = -0.04
        elif focus_mode == "singing":
            if item.activity_type == "singing":
                delta = 0.12
            elif item.activity_type in {"answering", "repeating"}:
                delta = -0.04
        elif focus_mode == "teacher_dialogue":
            if item.activity_type == "answering":
                delta = 0.1
            elif item.activity_type == "repeating":
                delta = -0.03

        confidence = min(0.99, max(0.0, item.confidence_score + delta))
        weighted.append(item.model_copy(update={"confidence_score": confidence}))
    return weighted


def merge_candidates(candidates: list[ActivityBlock], video_duration_sec: float) -> list[ActivityBlock]:
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda item: (item.start_time, item.end_time))
    merged: list[ActivityBlock] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start_time - previous.end_time <= 8:
            merged[-1] = ActivityBlock(
                candidate_id=previous.candidate_id,
                start_time=previous.start_time,
                end_time=min(video_duration_sec, max(previous.end_time, current.end_time)),
                activity_type=previous.activity_type if previous.confidence_score >= current.confidence_score else current.activity_type,
                confidence_score=max(previous.confidence_score, current.confidence_score),
                reason=f"{previous.reason} {current.reason}".strip(),
                transcript_excerpt=previous.transcript_excerpt,
            )
        else:
            merged.append(current)

    normalized: list[ActivityBlock] = []
    for item in merged:
        duration = item.end_time - item.start_time
        if duration < 20:
            pad = (20 - duration) / 2
            start_time = max(0.0, item.start_time - pad)
            end_time = min(video_duration_sec, item.end_time + pad)
            item = item.model_copy(update={"start_time": start_time, "end_time": end_time})
        if item.end_time - item.start_time > settings.max_clip_sec:
            center = (item.start_time + item.end_time) / 2
            half = settings.max_clip_sec / 2
            item = item.model_copy(
                update={
                    "start_time": max(0.0, center - half),
                    "end_time": min(video_duration_sec, center + half),
                }
            )
        if item.reason:
            item = item.model_copy(update={"reason": _normalize_reason(item.reason)})
        normalized.append(item)
    return normalized[:5]


def refine_candidates_with_gpt(
    segments: list[TranscriptSegment],
    candidates: list[ActivityBlock],
    video_duration_sec: float,
    options: ExtractionOptions | None = None,
) -> list[ActivityBlock]:
    if not candidates or not settings.openai_api_key:
        return candidates[:3]

    opts = options or ExtractionOptions()
    client = OpenAI(api_key=settings.openai_api_key)
    transcript_payload = [segment.model_dump(mode="json") for segment in segments]
    candidate_payload = [candidate.model_dump(mode="json") for candidate in candidates]

    prompt = """
You are an assistant that helps create highlight clips from English class videos.
The goal is to find moments where children are actively participating: answering, repeating, singing, chanting, playing, or responding in English.

Important:
- Prefer fewer, higher-quality clips.
- False positives are worse than missing a weak moment.
- Each final clip should be 30 to 120 seconds when possible.
- It is okay to return zero clips.
- Return JSON only.
""".strip()
    custom_instruction = (opts.custom_prompt or "").strip()
    if custom_instruction:
        prompt += "\n- User provided a custom selection instruction. Prioritize clips that satisfy it. If it conflicts with weak evidence, keep evidence quality first."

    response = client.responses.create(
        model=settings.openai_analysis_model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "video_duration_sec": video_duration_sec,
                                "transcript_segments": transcript_payload,
                                "candidate_windows": candidate_payload,
                                "user_custom_instruction": custom_instruction,
                                "output_schema": {
                                    "clips": [
                                        {
                                            "start_sec": 12.5,
                                            "end_sec": 67.0,
                                            "activity_type": "answering",
                                            "confidence_score": 0.84,
                                            "reason": "Teacher asks a question, children answer repeatedly, and teacher gives positive feedback.",
                                        }
                                    ]
                                },
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            },
        ],
    )

    text_output = getattr(response, "output_text", "") or ""
    if not text_output:
        return candidates[:3]

    try:
        payload = json.loads(text_output)
    except json.JSONDecodeError:
        return candidates[:3]

    refined: list[ActivityBlock] = []
    for clip in payload.get("clips", [])[:3]:
        try:
            refined.append(
                ActivityBlock(
                    candidate_id=clip.get("candidate_id"),
                    start_time=float(clip["start_sec"]),
                    end_time=float(clip["end_sec"]),
                    activity_type=str(clip.get("activity_type", "unknown")),
                    confidence_score=float(clip.get("confidence_score", 0.0)),
                    reason=str(clip.get("reason", "")),
                    transcript_excerpt=str(clip.get("transcript_excerpt", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return refined or candidates[:3]
