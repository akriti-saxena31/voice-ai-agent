"""
utils/config.py — Centralised environment configuration
=========================================================
Reads all required API keys and settings from the environment.
Supports both local .env files and Vercel-managed env vars
(POSTGRES_URL_NON_POOLING, KV_URL, etc.).

Call Config.validate() at startup to catch missing variables early.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Read-only namespace for environment variables."""

    # ── API keys ──────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")

    # ── Plivo telephony ───────────────────────────────────────────────────
    PLIVO_AUTH_ID: str = os.getenv("PLIVO_AUTH_ID", "")
    PLIVO_AUTH_TOKEN: str = os.getenv("PLIVO_AUTH_TOKEN", "")
    PLIVO_NUMBER: str = os.getenv("PLIVO_NUMBER", "")

    # ── Server / deployment ───────────────────────────────────────────────
    SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:8000")
    SILENCE_TIMEOUT_SECONDS: float = float(os.getenv("SILENCE_TIMEOUT_SECONDS", "15"))

    # When set, WebSocket streams route here instead of deriving from Host header.
    WEBSOCKET_BASE_URL: str = os.getenv("WEBSOCKET_BASE_URL", "")

    # ── PostgreSQL ────────────────────────────────────────────────────────
    # Vercel Postgres exposes POSTGRES_URL_NON_POOLING for direct connections
    POSTGRES_URL: str = (
        os.getenv("POSTGRES_URL_NON_POOLING")
        or os.getenv("POSTGRES_URL", "")
    )

    # ── Redis / Vercel KV ─────────────────────────────────────────────────
    REDIS_URL: str = (
        os.getenv("KV_URL")
        or os.getenv("REDIS_URL", "")
    )

    # ── Validation ────────────────────────────────────────────────────────
    _REQUIRED = [
        "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY",
        "PLIVO_AUTH_ID",
        "PLIVO_AUTH_TOKEN",
    ]

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of required env vars that are empty or unset."""
        return [k for k in cls._REQUIRED if not getattr(cls, k)]
