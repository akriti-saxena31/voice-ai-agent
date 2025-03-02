"""
tts_handler.py — ElevenLabs Text-to-Speech
============================================
Converts agent replies into mulaw 8 kHz audio suitable for Plivo
playback, with both one-shot and streaming modes.
"""

import logging
from typing import AsyncIterator

import httpx

from utils.config import Config
from utils.audio_utils import linear16_to_mulaw

log = logging.getLogger(__name__)

_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsTTS:
    """Synthesises speech via the ElevenLabs REST API."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self._voice_id = Config.ELEVENLABS_VOICE_ID

    async def synthesize(self, text: str) -> bytes:
        """Return the full utterance as mulaw 8 kHz bytes."""
        url = f"{_BASE_URL}/{self._voice_id}"
        headers = {
            "xi-api-key": Config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        }
        body = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        log.info("[%s] TTS -> \"%s\"", self.call_id, text[:80])

        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.post(
                    url, json=body, headers=headers, params={"output_format": "ulaw_8000"},
                )
                resp.raise_for_status()
                audio = resp.content

            log.info("[%s] TTS done — %d bytes (mulaw)", self.call_id, len(audio))
            return audio

        except httpx.HTTPStatusError as err:
            log.error(
                "[%s] ElevenLabs %d: %s",
                self.call_id, err.response.status_code, err.response.text[:200],
            )
            raise
        except Exception as err:
            log.error("[%s] TTS failed: %s", self.call_id, err)
            raise

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield mulaw audio chunks as they arrive from ElevenLabs."""
        url = f"{_BASE_URL}/{self._voice_id}/stream"
        headers = {
            "xi-api-key": Config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        }
        body = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            "output_format": "pcm_24000",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                async with http.stream("POST", url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    pcm_buf = bytearray()

                    async for chunk in resp.aiter_bytes(chunk_size=4800):
                        pcm_buf.extend(chunk)
                        while len(pcm_buf) >= 4800:
                            mulaw_chunk = linear16_to_mulaw(bytes(pcm_buf[:4800]), sample_rate=24000)
                            yield mulaw_chunk
                            pcm_buf = pcm_buf[4800:]

                    if pcm_buf:
                        yield linear16_to_mulaw(bytes(pcm_buf), sample_rate=24000)

        except Exception as err:
            log.error("[%s] TTS stream error: %s", self.call_id, err)
            raise
