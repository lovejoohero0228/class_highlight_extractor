from __future__ import annotations

from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import settings
from app.models import TranscriptSegment
from app.storage import load_json, save_json


def _normalize_segment(segment: dict[str, Any]) -> TranscriptSegment:
    return TranscriptSegment(
        start_time=float(segment.get("start") or segment.get("start_time") or 0.0),
        end_time=float(segment.get("end") or segment.get("end_time") or 0.0),
        text=str(segment.get("text") or "").strip(),
    )


def transcribe_audio(audio_path: Path, transcript_path: Path) -> list[TranscriptSegment]:
    if transcript_path.exists():
        payload = load_json(transcript_path)
        return [TranscriptSegment.model_validate(item) for item in payload]

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    with audio_path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model=settings.openai_transcribe_model,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    raw_segments = payload.get("segments") or []
    segments = [_normalize_segment(item) for item in raw_segments if str(item.get("text") or "").strip()]

    if not segments and payload.get("text"):
        segments = [
            TranscriptSegment(
                start_time=0.0,
                end_time=0.0,
                text=str(payload["text"]).strip(),
            )
        ]

    save_json(transcript_path, [segment.model_dump(mode="json") for segment in segments])
    return segments
