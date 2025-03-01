"""
stt_handler.py — Whisper Speech-to-Text Pipeline
==================================================
Accumulates raw PCM audio from the caller, detects speech / silence
boundaries, then ships completed utterances to OpenAI Whisper for
transcription.
"""

import asyncio
import io
import logging
import struct
import wave

from openai import AsyncOpenAI
from utils.config import Config

log = logging.getLogger(__name__)

_MIN_DURATION_SEC = 0.5
_MAX_DURATION_SEC = 8.0
_SILENCE_THRESHOLD = 300
_SILENCE_CHUNKS_NEEDED = 15


def _rms(pcm: bytes) -> float:
    """Root-mean-square loudness of a 16-bit PCM chunk."""
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5 if samples else 0.0


class WhisperSTT:
    """Buffers caller audio, detects utterance boundaries, transcribes via Whisper."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self._client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

        self._buf = bytearray()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()

        self._active = True
        self._speech_detected = False
        self._consecutive_silence = 0

    async def connect(self):
        self._active = True
        log.info("[%s] Whisper STT ready", self.call_id)

    async def send_audio(self, pcm_chunk: bytes):
        if not self._active:
            return

        loudness = _rms(pcm_chunk)

        if loudness > _SILENCE_THRESHOLD:
            self._speech_detected = True
            self._consecutive_silence = 0
        else:
            self._consecutive_silence += 1

        self._buf.extend(pcm_chunk)
        duration = len(self._buf) / (16_000 * 2)

        should_transcribe = self._speech_detected and (
            (self._consecutive_silence >= _SILENCE_CHUNKS_NEEDED and duration >= _MIN_DURATION_SEC)
            or duration >= _MAX_DURATION_SEC
        )

        if should_transcribe:
            await self._flush()

    async def _flush(self):
        async with self._lock:
            if not self._buf:
                return
            audio_bytes = bytes(self._buf)
            self._buf.clear()
            self._speech_detected = False
            self._consecutive_silence = 0

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16_000)
            wf.writeframes(audio_bytes)
        wav_io.seek(0)
        wav_io.name = "utterance.wav"

        try:
            result = await self._client.audio.transcriptions.create(
                model="whisper-1",
                file=wav_io,
                language="en",
            )
            text = result.text.strip()
            if text:
                log.info("[%s] STT transcript: %s", self.call_id, text)
                await self._queue.put(text)
        except Exception as exc:
            log.error("[%s] Whisper error: %s", self.call_id, exc)

    async def get_transcript(self, timeout: float = None) -> str | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def close(self):
        self._active = False
        if self._speech_detected and self._buf:
            await self._flush()
        log.info("[%s] Whisper STT closed", self.call_id)
