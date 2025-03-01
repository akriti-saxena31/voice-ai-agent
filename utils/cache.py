"""
utils/cache.py — Redis session management
===========================================
Each active call gets a short-lived Redis key that tracks the current
IVR step and links back to the Postgres call_log row. Sessions expire
after 30 minutes of inactivity.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from utils.config import Config

log = logging.getLogger(__name__)

_client: Optional[aioredis.Redis] = None
_TTL = 1800  # 30 minutes


async def init_redis():
    """Connect to Redis / Vercel KV. Call once on startup."""
    global _client
    if not Config.REDIS_URL:
        log.warning("REDIS_URL not set — session management disabled")
        return
    try:
        _client = aioredis.from_url(Config.REDIS_URL, decode_responses=True)
        await _client.ping()
        log.info("Redis connected")
    except Exception as exc:
        log.error("Redis connection failed: %s", exc)
        _client = None


async def close_redis():
    """Gracefully close the Redis connection."""
    global _client
    if _client:
        await _client.aclose()
        _client = None


def redis_client() -> Optional[aioredis.Redis]:
    """Return the current client (or None)."""
    return _client


def _key(call_uuid: str) -> str:
    return f"session:{call_uuid}"


async def create_session(call_uuid: str, caller: str, call_log_id: int = None):
    """Store a new session with a 30-minute TTL."""
    if not _client:
        return
    try:
        payload = {
            "caller_id": caller,
            "step": "main_menu",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "call_log_id": str(call_log_id) if call_log_id else "",
        }
        await _client.setex(_key(call_uuid), _TTL, json.dumps(payload))
    except Exception as exc:
        log.error("create_session: %s", exc)


async def get_session(call_uuid: str) -> dict:
    """Retrieve a session; returns {} if missing or Redis is down."""
    if not _client:
        return {}
    try:
        raw = await _client.get(_key(call_uuid))
        return json.loads(raw) if raw else {}
    except Exception as exc:
        log.error("get_session: %s", exc)
        return {}


async def update_session_step(call_uuid: str, step: str):
    """Update the step field and refresh the TTL."""
    if not _client:
        return
    try:
        session = await get_session(call_uuid)
        if session:
            session["step"] = step
            await _client.setex(_key(call_uuid), _TTL, json.dumps(session))
    except Exception as exc:
        log.error("update_session_step: %s", exc)


async def delete_session(call_uuid: str):
    """Remove a session key from Redis."""
    if not _client:
        return
    try:
        await _client.delete(_key(call_uuid))
    except Exception as exc:
        log.error("delete_session: %s", exc)
