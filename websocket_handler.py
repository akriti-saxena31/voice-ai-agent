"""
websocket_handler.py — Bidirectional Audio Pipeline
=====================================================
Manages the real-time audio loop for a single phone call:
    Caller mic -> mulaw decode -> Whisper STT -> GPT-4 -> ElevenLabs TTS -> Caller speaker
"""

import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from conversation_state import ConversationState, ConversationPhase
from stt_handler import WhisperSTT
from tts_handler import ElevenLabsTTS
from llm_handler import LLMHandler
from utils.audio_utils import (
    mulaw_to_linear16,
    base64_decode_audio,
    base64_encode_audio,
)
from utils.config import Config

log = logging.getLogger(__name__)

_CHUNK_BYTES = 640
_CHUNK_DELAY = 0.08


class CallHandler:
    """Owns every resource for one inbound call and drives the conversation."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.state = ConversationState(call_id=call_id)

        self.stt = WhisperSTT(call_id)
        self.tts = ElevenLabsTTS(call_id)
        self.llm = LLMHandler(call_id)

        self.plivo_ws: WebSocket | None = None
        self._speaking = False
        self._done = asyncio.Event()
        self._last_audio_ts = time.time()
        self._stream_id: str | None = None

    async def handle_websocket(self, ws: WebSocket):
        self.plivo_ws = ws
        await ws.accept()
        log.info("[%s] WS connected", self.call_id)

        try:
            await self.stt.connect()

            rx_task = asyncio.create_task(self._rx_loop())
            conv_task = asyncio.create_task(self._conv_loop())

            await self._greet()

            finished, remaining = await asyncio.wait(
                [rx_task, conv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in remaining:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        except WebSocketDisconnect:
            log.info("[%s] Caller hung up", self.call_id)
        except Exception as exc:
            log.error("[%s] WS error: %s", self.call_id, exc, exc_info=True)
        finally:
            await self._teardown()

    async def _rx_loop(self):
        try:
            while not self._done.is_set():
                raw = await self.plivo_ws.receive_text()
                frame = json.loads(raw)
                kind = frame.get("event")

                if kind == "start":
                    self._stream_id = frame.get("start", {}).get("streamId")
                    log.info("[%s] Stream started (id=%s)", self.call_id, self._stream_id)

                elif kind == "media":
                    if self._speaking:
                        continue
                    payload = frame.get("media", {}).get("payload", "")
                    if payload:
                        raw_mulaw = base64_decode_audio(payload)
                        pcm = mulaw_to_linear16(raw_mulaw)
                        await self.stt.send_audio(pcm)
                        self._last_audio_ts = time.time()

                elif kind == "stop":
                    log.info("[%s] Stream stopped by Plivo", self.call_id)
                    self._done.set()
                    break

        except WebSocketDisconnect:
            log.info("[%s] Plivo WS closed", self.call_id)
            self._done.set()
        except Exception as exc:
            log.error("[%s] RX error: %s", self.call_id, exc)
            self._done.set()

    async def _conv_loop(self):
        try:
            while not self._done.is_set():
                transcript = await self.stt.get_transcript(
                    timeout=Config.SILENCE_TIMEOUT_SECONDS
                )

                if transcript is None:
                    idle = time.time() - self._last_audio_ts
                    if idle > Config.SILENCE_TIMEOUT_SECONDS:
                        log.info("[%s] Silence timeout (%.1fs)", self.call_id, idle)
                        await self._say("Are you still there? I didn't catch that.")
                    continue

                if not transcript.strip():
                    continue

                log.info("[%s] Caller: %s", self.call_id, transcript)
                self._speaking = True

                try:
                    reply = await self.llm.get_response(self.state, caller_text=transcript)
                except Exception as exc:
                    log.warning("[%s] LLM error, falling back: %s", self.call_id, exc)
                    reply = (
                        f"I heard you say: {transcript}. "
                        "I'm having some trouble with my system right now, but I'll be right with you."
                    )

                await self._say(reply)

                if self.state.phase == ConversationPhase.COMPLETED:
                    log.info("[%s] Reservation finalised!", self.call_id)
                    await asyncio.sleep(2)
                    self._done.set()
                    break

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("[%s] Conv loop error: %s", self.call_id, exc, exc_info=True)
            self._done.set()

    async def _greet(self):
        try:
            text = await self.llm.get_greeting(self.state)
        except Exception as exc:
            log.warning("[%s] Greeting LLM failed, using fallback: %s", self.call_id, exc)
            text = (
                "Hi, thanks for calling Mario's Italian Kitchen! "
                "I can help you make a reservation. What date were you thinking?"
            )
            self.state.add_message("assistant", text)

        log.info("[%s] Greeting ready", self.call_id)
        await self._say(text)

    async def _say(self, text: str):
        if not text:
            return

        self._speaking = True
        try:
            audio = await self.tts.synthesize(text)
            log.info("[%s] Sending %d bytes to caller", self.call_id, len(audio))

            for offset in range(0, len(audio), _CHUNK_BYTES):
                if self._done.is_set():
                    break
                chunk = audio[offset: offset + _CHUNK_BYTES]
                b64 = base64_encode_audio(chunk)
                await self.plivo_ws.send_text(json.dumps({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": b64,
                    },
                }))
                await asyncio.sleep(_CHUNK_DELAY)

        except Exception as exc:
            log.error("[%s] Playback error: %s", self.call_id, exc)
        finally:
            self._speaking = False
            self.stt._buf.clear()
            self.stt._speech_detected = False
            self.stt._consecutive_silence = 0
            while not self.stt._queue.empty():
                try:
                    self.stt._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    async def _teardown(self):
        log.info("[%s] Tearing down", self.call_id)
        await self.stt.close()
        try:
            await self.plivo_ws.close()
        except Exception:
            pass
        log.info("[%s] Final state:\n%s", self.call_id, self.state.get_state_summary())
