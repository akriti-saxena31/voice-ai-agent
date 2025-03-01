"""
utils/audio_utils.py — Audio encoding / decoding helpers
==========================================================
Handles the mulaw <-> linear16 conversions and base64 wrapping
needed to shuttle audio between Plivo and the STT/TTS services.
"""

import audioop
import base64


def mulaw_to_linear16(mulaw_bytes: bytes, *, sample_rate: int = 8000) -> bytes:
    """Decode mulaw 8 kHz -> linear16 PCM 16 kHz (what Whisper expects)."""
    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
    pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, sample_rate, 16000, None)
    return pcm_16k


def linear16_to_mulaw(pcm_bytes: bytes, *, sample_rate: int = 16000) -> bytes:
    """Encode linear16 PCM -> mulaw 8 kHz (what Plivo expects)."""
    if sample_rate != 8000:
        pcm_bytes, _ = audioop.ratecv(pcm_bytes, 2, 1, sample_rate, 8000, None)
    return audioop.lin2ulaw(pcm_bytes, 2)


def base64_decode_audio(payload: str) -> bytes:
    """Unwrap a base64 string into raw audio bytes."""
    return base64.b64decode(payload)


def base64_encode_audio(audio_bytes: bytes) -> str:
    """Wrap raw audio bytes as a base64 string for JSON transport."""
    return base64.b64encode(audio_bytes).decode("ascii")
