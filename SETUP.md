# Setup Guide

See the README for a quick start. This guide covers detailed setup and troubleshooting.

## Local Development

### 1. PostgreSQL + Redis via Docker

```bash
docker run -d --name pg -p 5432:5432 \
  -e POSTGRES_USER=mario -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=marios_db postgres:16

docker run -d --name redis -p 6379:6379 redis:7
```

Set in `.env`:
```
POSTGRES_URL=postgresql://mario:secret@localhost:5432/marios_db
REDIS_URL=redis://localhost:6379/0
```

### 2. Create the DB table

```bash
curl http://localhost:8000/api/setup-db
```

### 3. Expose for Plivo

```bash
ngrok http 8000
```

Set `SERVER_URL` and `WEBSOCKET_BASE_URL` in `.env` to the ngrok URL.

## Vercel Deployment

1. Add Vercel Postgres and Vercel KV from the Storage tab
2. Set env vars in the dashboard (see `.env.example`)
3. Deploy with `vercel`
4. Deploy WebSocket server separately on Railway
5. Set `WEBSOCKET_BASE_URL` to your Railway URL

## Troubleshooting

- **PyAudio install fails**: `brew install portaudio` (macOS) or `sudo apt install python3-pyaudio` (Ubuntu)
- **No agent audio**: Check ElevenLabs key and voice ID
- **IVR works but press-1 fails**: Verify `/handle-input` is reachable
- **No call logs**: Run `/api/setup-db` first, check `/api/health`
- **SMS not sending**: Verify PLIVO_NUMBER has SMS capability
