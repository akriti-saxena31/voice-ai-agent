"""
Mario's Italian Kitchen — Voice AI Reservation Agent
=====================================================
FastAPI application that handles inbound phone calls via Plivo,
streams audio through a WebSocket pipeline:
    Plivo -> Deepgram (STT) -> GPT-4o-mini (LLM) -> ElevenLabs (TTS) -> Plivo

Includes:
  - IVR menu for routing (reservations / hours / transfer)
  - PostgreSQL call logging
  - Redis session management
  - SMS booking confirmations via Plivo
"""

import logging
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

from plivo_webhook import router as plivo_router
from websocket_handler import CallHandler
from utils.config import Config
from utils.db import init_pg, close_pg, pg_pool
from utils.cache import init_redis, close_redis, redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_missing = Config.validate()
if _missing:
    log.warning(
        "Environment variables not set: %s. "
        "Copy .env.example -> .env and add your API keys.",
        ", ".join(_missing),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pg()
    await init_redis()
    yield
    await close_pg()
    await close_redis()


app = FastAPI(
    title="Mario's Italian Kitchen — Voice AI Agent",
    description=(
        "Inbound call reservation system powered by "
        "Plivo, Deepgram, GPT-4o-mini, and ElevenLabs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(plivo_router)

_live_calls: dict[str, CallHandler] = {}


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Mario's Italian Kitchen — Voice AI Agent",
        "live_calls": len(_live_calls),
    }


@app.websocket("/ws/audio/{call_id}")
async def ws_audio(websocket: WebSocket, call_id: str):
    call_id = call_id or str(uuid.uuid4())
    log.info("WebSocket opened — call_id=%s", call_id)

    handler = CallHandler(call_id)
    _live_calls[call_id] = handler

    try:
        await handler.handle_websocket(websocket)
    finally:
        _live_calls.pop(call_id, None)
        log.info("Call %s cleaned up. Live calls: %d", call_id, len(_live_calls))


@app.get("/calls")
async def list_calls():
    result = []
    for cid, h in _live_calls.items():
        result.append({
            "call_id": cid,
            "phase": h.state.phase.value,
            "reservation": {
                "date": h.state.reservation.date,
                "time": h.state.reservation.time,
                "party_size": h.state.reservation.party_size,
                "name": h.state.reservation.name,
            },
        })
    return {"active_calls": result}


@app.get("/api/setup-db")
async def setup_db():
    pool = pg_pool()
    if not pool:
        return JSONResponse({"error": "Database not configured"}, status_code=503)
    try:
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id                 SERIAL PRIMARY KEY,
                caller_number      VARCHAR(20),
                called_number      VARCHAR(20),
                call_status        VARCHAR(50),
                detected_intent    VARCHAR(50),
                transcript_summary TEXT,
                duration_seconds   INTEGER,
                created_at         TIMESTAMP DEFAULT NOW()
            )
        """)
        return {"message": "call_logs table ready"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/recent-calls")
async def recent_calls():
    pool = pg_pool()
    if not pool:
        return JSONResponse({"error": "Database not configured"}, status_code=503)
    try:
        rows = await pool.fetch(
            """SELECT id, caller_number, called_number, call_status,
                      detected_intent, transcript_summary, duration_seconds, created_at
               FROM call_logs ORDER BY created_at DESC LIMIT 20"""
        )
        calls = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            calls.append(r)
        return {"total": len(calls), "calls": calls}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/health")
async def health():
    from datetime import datetime, timezone
    result = {
        "status": "healthy",
        "redis": "ok",
        "postgres": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    rc = redis_client()
    if rc:
        try:
            await rc.ping()
        except Exception:
            result["redis"] = "error"
            result["status"] = "degraded"
    else:
        result["redis"] = "not configured"

    pool = pg_pool()
    if pool:
        try:
            await pool.fetchval("SELECT 1")
        except Exception:
            result["postgres"] = "error"
            result["status"] = "degraded"
    else:
        result["postgres"] = "not configured"

    return result


@app.get("/call-history/{phone}")
async def call_history(phone: str):
    pool = pg_pool()
    if not pool:
        return JSONResponse({"error": "Database not configured"}, status_code=503)
    try:
        rows = await pool.fetch(
            """SELECT id, caller_number, called_number, call_status,
                      detected_intent, transcript_summary, duration_seconds, created_at
               FROM call_logs WHERE caller_number=$1
               ORDER BY created_at DESC""",
            phone,
        )
        calls = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            calls.append(r)
        return {"phone_number": phone, "calls": calls}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
