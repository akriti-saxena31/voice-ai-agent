# Voice AI Agent — Mario's Italian Kitchen

An AI-powered phone reservation system that handles inbound calls end-to-end. Callers interact with an IVR menu and can speak naturally to an AI agent that books their table.

Built as a real-time audio pipeline: **Plivo** (telephony) → **Deepgram** (STT) → **GPT-4o-mini** (reasoning) → **ElevenLabs** (TTS) → back to the caller. Call state is tracked in **Redis**, call logs persist in **PostgreSQL**, and confirmed bookings trigger an **SMS confirmation**.

## How It Works

1. Caller dials the restaurant's Plivo number
2. An **IVR menu** greets them: *Press 1 for Reservations, 2 for Hours, 3 to transfer*
3. If they press **1**, Plivo opens a bidirectional WebSocket to this server
4. The caller's voice streams as mulaw audio → decoded → fed to **Whisper STT**
5. The transcript goes to **GPT-4o-mini**, which tracks conversation context and extracts reservation details (date, time, party size, name)
6. The model's reply is synthesised by **ElevenLabs TTS**
7. Audio is chunked and streamed back to the caller in real-time
8. On confirmation, the call is logged to **PostgreSQL** and an **SMS** is sent via Plivo

## Tech Stack

| Layer | Technology |
|---|---|
| Telephony + SMS | Plivo |
| Speech-to-Text | OpenAI Whisper |
| Conversation AI | OpenAI GPT-4o-mini |
| Text-to-Speech | ElevenLabs Turbo v2 |
| Session Store | Redis (Vercel KV in production) |
| Call Logging | PostgreSQL (Vercel Postgres in production) |
| Server | FastAPI + Uvicorn |
| Deployment | Vercel (HTTP) + Railway (WebSockets) |

## Project Structure

\`\`\`
voice-ai-agent/
├── main.py                   # FastAPI app, lifespan, health/debug endpoints
├── websocket_handler.py      # Full audio pipeline for a single call
├── conversation_state.py     # State machine — tracks reservation progress
├── llm_handler.py            # GPT-4o-mini conversation engine
├── stt_handler.py            # Whisper STT with silence detection
├── tts_handler.py            # ElevenLabs TTS (one-shot + streaming)
├── plivo_webhook.py          # IVR menu, DTMF routing, /answer + /hangup
├── utils/
│   ├── __init__.py
│   ├── config.py             # Env vars (Vercel + local aware)
│   ├── db.py                 # PostgreSQL pool + call-log CRUD
│   ├── cache.py              # Redis session management
│   ├── sms.py                # Plivo SMS confirmations
│   └── audio_utils.py        # mulaw/linear16/base64 helpers
├── vercel.json               # Vercel deployment config
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── SETUP.md
\`\`\`

## Getting Started

### Prerequisites

- Python 3.10+
- A Plivo account with a phone number
- API keys for: OpenAI, ElevenLabs
- PostgreSQL instance (local or Vercel Postgres)
- Redis instance (local or Vercel KV)

### Local Setup

\`\`\`bash
git clone https://github.com/akriti-saxena31/voice-ai-agent.git
cd voice-ai-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys
\`\`\`

Create the database table:

\`\`\`bash
python main.py &
curl http://localhost:8000/api/setup-db
\`\`\`

Expose your local server:

\`\`\`bash
ngrok http 8000
\`\`\`

Configure Plivo: Answer URL → \`https://your-ngrok.ngrok.io/answer\`, Hangup URL → \`https://your-ngrok.ngrok.io/hangup\`

### Vercel Deployment

\`\`\`bash
npm i -g vercel
vercel
\`\`\`

**Note:** Vercel serverless functions don't support persistent WebSockets. Deploy a separate WebSocket server on Railway and set \`WEBSOCKET_BASE_URL\` accordingly.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | \`/\` | Health check |
| POST | \`/answer\` | Plivo answer webhook (IVR) |
| POST | \`/handle-input\` | DTMF routing |
| POST | \`/hangup\` | Hangup webhook |
| WS | \`/ws/audio/{call_id}\` | Audio stream |
| GET | \`/api/setup-db\` | Create call_logs table |
| GET | \`/api/recent-calls\` | Last 20 calls |
| GET | \`/api/health\` | Redis + Postgres status |
| GET | \`/call-history/{phone}\` | History for a number |
| GET | \`/calls\` | Active calls |

## Features

- **IVR menu** — press 1/2/3 to route calls
- **Natural conversation** — one piece of info at a time
- **Silence detection** — custom VAD triggers transcription after speech ends
- **Barge-in prevention** — ignores mic while agent speaks
- **PostgreSQL logging** — call status, intent, duration, transcript
- **Redis sessions** — state survives across webhook hops (30-min TTL)
- **SMS confirmations** — text recap after booking
- **Vercel-ready** — auto-detects managed Postgres and KV

---

Built by [@akriti-saxena31](https://github.com/akriti-saxena31)
