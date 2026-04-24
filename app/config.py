from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_title: str = "DearSunshine"
    data_dir: Path = Path("./data")
    max_upload_mb: int = 1000
    openai_api_key: str = ""
    openai_transcribe_model: str = "whisper-1"
    openai_analysis_model: str = "gpt-4o-mini"
    min_clip_sec: int = 30
    max_clip_sec: int = 120
    start_padding_sec: int = 2
    end_padding_sec: int = 3
    job_poll_seconds: int = Field(default=3, ge=1)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.uploads_dir,
            self.audio_dir,
            self.transcripts_dir,
            self.jobs_dir,
            self.clips_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
