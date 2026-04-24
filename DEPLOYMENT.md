# Deployment

This app is a FastAPI server with a static frontend. The easiest path to make it reachable on iPhone anywhere is to run it as a container on a PaaS such as Render or Fly.io.

## Required environment variables

- `OPENAI_API_KEY`: required for transcription and highlight analysis
- `DATA_DIR`: directory for uploads, transcripts, jobs, and clips

## Notes

- The app needs `ffmpeg` installed in the runtime image.
- `DATA_DIR` should point to persistent storage, not ephemeral disk, if you want uploads and results to survive restarts.
- The `/api/jobs` endpoint drives the frontend polling, so the public URL must allow normal browser access over HTTPS.

## Render

1. Create a new Web Service from the repository.
2. Let Render use [`render.yaml`](./render.yaml) as the Blueprint.
3. Add the `OPENAI_API_KEY` value when prompted.
4. Deploy and open the generated HTTPS URL on iPhone Safari.

## Fly.io

1. Create an app from the repository.
2. Use [`fly.toml`](./fly.toml) as the app config.
3. Create the volume named `dearsunshine_data` with `fly volumes create dearsunshine_data`.
4. Add `OPENAI_API_KEY` as a secret.
5. Deploy and use the generated HTTPS URL on iPhone Safari.
