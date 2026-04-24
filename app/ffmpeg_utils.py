from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class FFmpegError(RuntimeError):
    """Raised when ffmpeg or ffprobe processing fails."""


def ensure_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise FFmpegError(f"Missing required binaries in PATH: {', '.join(missing)}")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Unknown ffmpeg error"
        raise FFmpegError(detail)
    return result


def probe_video(input_path: Path) -> dict[str, object]:
    ensure_ffmpeg()
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(input_path),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    duration = float(payload.get("format", {}).get("duration") or 0.0)
    orientation = "unknown"
    if width and height:
        orientation = "portrait" if height > width else "landscape"
    return {
        "duration_seconds": duration,
        "orientation": orientation,
    }


def extract_audio(input_path: Path, output_path: Path) -> Path:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
    )
    return output_path


def create_clip(input_path: Path, output_path: Path, start_sec: float, end_sec: float) -> Path:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_sec:.3f}",
            "-to",
            f"{end_sec:.3f}",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return output_path


def concat_clips(input_paths: list[Path], output_path: Path) -> Path:
    ensure_ffmpeg()
    if not input_paths:
        raise FFmpegError("No input clips provided for merge")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as list_file:
        list_path = Path(list_file.name)
        for path in input_paths:
            normalized = str(path.resolve()).replace("'", "'\\''")
            list_file.write(f"file '{normalized}'\n")

    try:
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    finally:
        list_path.unlink(missing_ok=True)

    return output_path
