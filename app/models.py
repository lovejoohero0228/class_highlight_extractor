from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ClipStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    deleted = "deleted"


class VideoMetadata(BaseModel):
    video_id: str
    original_filename: str
    source_path: str
    duration_seconds: float | None = None
    orientation: Literal["landscape", "portrait", "unknown"] = "unknown"


class TranscriptSegment(BaseModel):
    start_time: float
    end_time: float
    text: str


class ActivityBlock(BaseModel):
    candidate_id: str | None = None
    start_time: float
    end_time: float
    activity_type: Literal["answering", "singing", "repeating", "playing", "unknown"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    transcript_excerpt: str = ""


class CandidateReview(BaseModel):
    candidate_id: str
    start_time: float
    end_time: float
    activity_type: str
    confidence_score: float
    reason: str = ""
    transcript_excerpt: str = ""
    selected: bool = False


class Clip(BaseModel):
    clip_id: str
    video_id: str
    source_candidate_id: str | None = None
    clip_start: float
    clip_end: float
    clip_duration: float
    activity_type: str
    confidence_score: float
    clip_status: ClipStatus = ClipStatus.pending
    output_path: str
    preview_url: str | None = None
    download_url: str | None = None
    transcript_excerpt: str = ""
    explain_text: str = ""


class ExtractionOptions(BaseModel):
    focus_mode: Literal["balanced", "kids_talk", "singing", "teacher_dialogue"] = "balanced"
    clip_shape: Literal["fit", "buffer_3s", "buffer_5s"] = "fit"
    custom_prompt: str = ""


class Job(BaseModel):
    job_id: str
    request_group_id: str = ""
    request_label: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: JobStatus
    video: VideoMetadata
    progress: int = 0
    message: str = ""
    options: ExtractionOptions = Field(default_factory=ExtractionOptions)
    transcript_path: str | None = None
    clips: list[Clip] = Field(default_factory=list)
    candidate_reviews: list[CandidateReview] = Field(default_factory=list)
    error: str | None = None
