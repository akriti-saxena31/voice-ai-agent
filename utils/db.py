"""
utils/db.py — PostgreSQL connection pool and call-log helpers
==============================================================
Manages a shared asyncpg pool initialised during app lifespan.
All helpers are no-ops when the pool is unavailable (no DB configured).
"""

import logging
from typing import Optional

import asyncpg

from utils.config import Config

log = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pg():
    """Create the connection pool. Call once on startup."""
    global _pool
    if not Config.POSTGRES_URL:
        log.warning("POSTGRES_URL not set — call logging disabled")
        return
    try:
        _pool = await asyncpg.create_pool(Config.POSTGRES_URL)
        log.info("PostgreSQL connected")
    except Exception as exc:
        log.error("PostgreSQL connection failed: %s", exc)


async def close_pg():
    """Drain and close the pool. Call on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def pg_pool() -> Optional[asyncpg.Pool]:
    """Return the current pool (or None)."""
    return _pool


async def log_call_start(caller: str, callee: str) -> Optional[int]:
    """Insert a new row in call_logs and return its id."""
    if not _pool:
        return None
    try:
        return await _pool.fetchval(
            """INSERT INTO call_logs (caller_number, called_number, call_status, created_at)
               VALUES ($1, $2, 'started', NOW()) RETURNING id""",
            caller, callee,
        )
    except Exception as exc:
        log.error("log_call_start: %s", exc)
        return None


async def update_call_intent(call_log_id: Optional[int], intent: str, status: str = None):
    """Set the detected_intent (and optionally call_status) on a row."""
    if not _pool or not call_log_id:
        return
    try:
        if status:
            await _pool.execute(
                "UPDATE call_logs SET detected_intent=$1, call_status=$2 WHERE id=$3",
                intent, status, call_log_id,
            )
        else:
            await _pool.execute(
                "UPDATE call_logs SET detected_intent=$1 WHERE id=$2",
                intent, call_log_id,
            )
    except Exception as exc:
        log.error("update_call_intent: %s", exc)


async def finalize_call_log(call_log_id: Optional[int], duration: Optional[int], summary: str = None):
    """Mark a call as completed with duration and optional transcript summary."""
    if not _pool or not call_log_id:
        return
    try:
        await _pool.execute(
            """UPDATE call_logs
               SET call_status='completed', duration_seconds=$1, transcript_summary=$2
               WHERE id=$3 AND call_status='started'""",
            duration, summary, call_log_id,
        )
    except Exception as exc:
        log.error("finalize_call_log: %s", exc)
