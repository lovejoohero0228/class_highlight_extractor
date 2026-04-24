from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.ffmpeg_utils import FFmpegError, concat_clips
from app.models import ClipStatus, ExtractionOptions, Job
from app.pipeline import process_video
from app.storage import create_job, find_clip, get_job, list_jobs, save_job

app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
APP_STARTED_AT = datetime.now(timezone.utc)


class MergeRequest(BaseModel):
    clip_ids: list[str] = Field(default_factory=list)


def _parse_job_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return APP_STARTED_AT


def _serialize_job(job: Job) -> dict[str, object]:
    payload = job.model_dump(mode="json")
    reference_time = _parse_job_time(job.created_at or job.updated_at)
    payload["archived"] = job.request_group_id.startswith("legacy_") or reference_time < APP_STARTED_AT
    return payload


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "merged").stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned or "merged"


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/api/videos")
async def upload_video(
    background_tasks: BackgroundTasks,
    request_group_id: str = Form(""),
    request_label: str = Form(""),
    custom_prompt: str = Form(""),
    clip_shape: str = Form("fit"),
    file: UploadFile = File(...),
) -> dict[str, str]:
    filename = (file.filename or "").lower()
    if not filename.endswith((".mp4", ".mov", ".m4v")):
        raise HTTPException(status_code=400, detail="MP4, MOV, M4V 영상만 업로드할 수 있습니다")

    try:
        options = ExtractionOptions(
            custom_prompt=custom_prompt.strip(),
            clip_shape=clip_shape,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"옵션 값이 유효하지 않습니다: {exc}") from exc

    job = await create_job(
        file,
        request_group_id=request_group_id,
        request_label=request_label,
        options=options,
    )
    background_tasks.add_task(process_video, job.job_id)
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "request_group_id": job.request_group_id,
    }


@app.get("/api/jobs")
def api_list_jobs():
    return [_serialize_job(job) for job in list_jobs()]


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return _serialize_job(job)


@app.delete("/api/clips/{clip_id}")
def api_delete_clip(clip_id: str) -> dict[str, bool]:
    clip, job = find_clip(clip_id)
    if not clip or not job:
        raise HTTPException(status_code=404, detail="클립을 찾을 수 없습니다")
    for item in job.clips:
        if item.clip_id == clip_id:
            item.clip_status = ClipStatus.deleted
            break
    save_job(job)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/merge-download")
def api_merge_download(job_id: str, body: MergeRequest):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    selected = []
    seen: set[str] = set()
    for clip_id in body.clip_ids:
        if not clip_id or clip_id in seen:
            continue
        seen.add(clip_id)
        selected.append(clip_id)
    if not selected:
        raise HTTPException(status_code=400, detail="합칠 클립을 하나 이상 선택해주세요")

    clip_map = {clip.clip_id: clip for clip in job.clips if clip.clip_status != ClipStatus.deleted}
    chosen_clips = []
    for clip_id in selected:
        clip = clip_map.get(clip_id)
        if not clip:
            raise HTTPException(status_code=400, detail=f"선택한 클립을 찾을 수 없습니다: {clip_id}")
        clip_path = Path(clip.output_path)
        if not clip_path.exists():
            raise HTTPException(status_code=400, detail=f"클립 파일이 존재하지 않습니다: {clip_id}")
        chosen_clips.append(clip)

    input_paths = [Path(clip.output_path) for clip in chosen_clips]
    merged_dir = settings.clips_dir / job.job_id / "merged"
    merged_path = merged_dir / f"merged_{uuid4().hex[:12]}.mp4"

    try:
        concat_clips(input_paths, merged_path)
    except FFmpegError as exc:
        raise HTTPException(status_code=500, detail=f"영상 합치기에 실패했습니다: {exc}") from exc

    base = _safe_stem(job.video.original_filename)
    return FileResponse(
        str(merged_path.resolve()),
        media_type="video/mp4",
        filename=f"dearsunshine_{base}_merged.mp4",
    )


@app.get("/api/clips/{clip_id}/preview")
def api_preview_clip(clip_id: str) -> FileResponse:
    clip, _ = find_clip(clip_id)
    if not clip or clip.clip_status == ClipStatus.deleted or not Path(clip.output_path).exists():
        raise HTTPException(status_code=404, detail="클립을 찾을 수 없습니다")
    return FileResponse(clip.output_path, media_type="video/mp4")


@app.get("/api/clips/{clip_id}/download")
def api_download_clip(clip_id: str) -> FileResponse:
    clip, _ = find_clip(clip_id)
    if not clip or clip.clip_status == ClipStatus.deleted or not Path(clip.output_path).exists():
        raise HTTPException(status_code=404, detail="클립을 찾을 수 없습니다")
    return FileResponse(
        clip.output_path,
        media_type="video/mp4",
        filename=f"dearsunshine_{clip.clip_id}.mp4",
    )
