# Deployment

This app is a FastAPI server with a static frontend and is ready to deploy to Render.

## Required environment variables

- `OPENAI_API_KEY`: required for transcription/highlight analysis
- `DATA_DIR`: set to `/data` on Render (already declared in `render.yaml`)

## Render (recommended)

Repository already includes [`render.yaml`](./render.yaml) with:

- Docker runtime (`Dockerfile`)
- `free` plan
- `DATA_DIR=/data`
- health check path `/healthz`

Deploy steps:

1. Render dashboard -> `New` -> `Blueprint`.
2. Connect `lovejoohero0228/class_highlight_extractor`.
3. Confirm the service from `render.yaml` and create it.
4. In service settings, set `OPENAI_API_KEY`.
5. Deploy and wait until health check `/healthz` is passing.
6. Open the generated `https://...onrender.com` URL in iPhone Safari.

## iPhone Safari notes

- Always access with `https://` URL (Render default domain is HTTPS).
- Large video upload depends on network quality; use stable Wi-Fi for better reliability.
- On free plan, app data is ephemeral and may reset after redeploy/restart.

## Fly.io (optional)

`fly.toml` is included if you want Fly deployment instead.
