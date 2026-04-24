from __future__ import annotations

from uuid import uuid4

from app.config import settings
from app.models import ActivityBlock, Clip


def normalize_blocks(blocks: list[ActivityBlock], duration_seconds: float, video_id: str) -> list[Clip]:
    normalized: list[Clip] = []
    for index, block in enumerate(sorted(blocks, key=lambda item: item.confidence_score, reverse=True), start=1):
        if block.confidence_score < 0.55:
            continue

        start = max(0.0, block.start_time - settings.start_padding_sec)
        end = min(duration_seconds, block.end_time + settings.end_padding_sec)
        clip_duration = end - start

        if clip_duration < settings.min_clip_sec:
            center = (start + end) / 2
            half = settings.min_clip_sec / 2
            start = max(0.0, center - half)
            end = min(duration_seconds, center + half)

        if end - start > settings.max_clip_sec:
            center = (start + end) / 2
            half = settings.max_clip_sec / 2
            start = max(0.0, center - half)
            end = min(duration_seconds, center + half)

        if start >= end:
            continue

        normalized.append(
            Clip(
                clip_id=f"clip_{uuid4().hex[:12]}",
                video_id=video_id,
                source_candidate_id=block.candidate_id,
                clip_start=round(start, 3),
                clip_end=round(end, 3),
                clip_duration=round(end - start, 3),
                activity_type=block.activity_type,
                confidence_score=round(block.confidence_score, 3),
                output_path="",
                transcript_excerpt=block.transcript_excerpt,
                explain_text=block.reason,
            )
        )
        if len(normalized) >= 3:
            break
    return normalized
