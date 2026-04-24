# DearSunshine

DearSunshine is a local FastAPI app that uploads English class videos, transcribes them with OpenAI, detects likely child participation moments, renders 0 to 3 highlight clips with ffmpeg, and lets you preview, delete, or download those clips from a mobile-friendly web UI.

## Requirements

- Windows 11 or another OS with Python 3.11+
- `ffmpeg` and `ffprobe` available in `PATH`
- OpenAI API key in `.env`

## Setup

```bash
conda create -n dearsunshine python=3.11 -y
conda activate dearsunshine
pip install -r requirements.txt
copy .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

Install ffmpeg on Windows if needed:

```bash
winget install Gyan.FFmpeg
```

Confirm the binaries are available:

```bash
ffmpeg -version
ffprobe -version
```

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

- Local machine: `http://localhost:8000`
- Phone on same Wi-Fi: `http://<PC_LOCAL_IP>:8000`

## Render Deploy

This repository includes [`render.yaml`](./render.yaml) and [`Dockerfile`](./Dockerfile).

1. Push latest code to GitHub.
2. In Render, create a `Blueprint` from this repository.
3. Set `OPENAI_API_KEY` in Render environment variables.
4. Deploy, then open the Render HTTPS URL in iPhone Safari.

## Data Layout

Generated data is stored under `./data`:

- `uploads/`
- `audio/`
- `transcripts/`
- `jobs/`
- `clips/`

## Notes

- Transcript JSON is cached by `job_id` after the first successful transcription.
- GPT refinement is used only when `OPENAI_API_KEY` is configured.
- Clip deletion is soft delete only. The file stays on disk and is hidden from the UI.
