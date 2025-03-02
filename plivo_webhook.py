"""
plivo_webhook.py — Plivo Inbound Call Webhooks + IVR Menu
==========================================================
When Plivo receives a call it hits /answer. We return an IVR menu
(press 1 / 2 / 3). Based on the digit, /handle-input either launches
the AI voice agent, reads store info, or "transfers" the caller.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import Response

from utils.config import Config
from utils.db import log_call_start, update_call_intent, finalize_call_log
from utils.cache import create_session, get_session, update_session_step, delete_session
from utils.sms import send_reservation_sms
from conversation_state import ConversationState

log = logging.getLogger(__name__)

router = APIRouter()

_conversations: dict[str, ConversationState] = {}

_IVR_BODY = (
    "Welcome to Mario's Italian Kitchen. "
    "Press 1 for Reservations. "
    "Press 2 for Hours and Location. "
    "Press 3 to speak with someone."
)


def _menu_xml(host: str, preamble: str = "") -> str:
    text = f"{preamble} {_IVR_BODY}" if preamble else _IVR_BODY
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <GetDigits action="https://{host}/handle-input" method="POST"
               numDigits="1" timeout="10" retries="3">
        <Speak>{text}</Speak>
    </GetDigits>
    <Speak>We didn't receive your input. Goodbye!</Speak>
</Response>"""


async def _params(request: Request) -> dict:
    merged = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        merged.update(form)
    return merged


def get_conversations() -> dict[str, ConversationState]:
    return _conversations


@router.post("/webhook/answer")
@router.get("/webhook/answer")
@router.post("/answer")
@router.get("/answer")
async def answer_call(request: Request):
    p = await _params(request)
    call_uuid = p.get("CallUUID", "unknown")
    caller = p.get("From", "unknown")
    callee = p.get("To", Config.PLIVO_NUMBER)

    log.info("Inbound call %s  %s -> %s", call_uuid, caller, callee)

    call_log_id = await log_call_start(caller, callee)
    await create_session(call_uuid, caller, call_log_id)

    host = request.headers.get("host", "localhost:8000")
    return Response(content=_menu_xml(host), media_type="application/xml")


@router.post("/handle-input")
async def handle_input(request: Request):
    p = await _params(request)
    call_uuid = p.get("CallUUID", "unknown")
    caller = p.get("From", "unknown")
    digit = p.get("Digits", "")
    host = request.headers.get("host", "localhost:8000")

    log.info("DTMF '%s' from %s (call %s)", digit, caller, call_uuid)

    session = await get_session(call_uuid)
    raw_id = session.get("call_log_id", "")
    call_log_id = int(raw_id) if raw_id else None

    if digit == "1":
        await update_session_step(call_uuid, "reservations")
        await update_call_intent(call_log_id, "reservations")

        conv = ConversationState(call_id=call_uuid)
        conv.caller_number = caller
        conv.call_log_id = call_log_id
        _conversations[call_uuid] = conv

        ws_base = Config.WEBSOCKET_BASE_URL or f"wss://{host}"
        stream_url = f"{ws_base}/ws/audio/{call_uuid}"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true"
            contentType="audio/x-mulaw;rate=8000">{stream_url}</Stream>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    if digit == "2":
        await update_session_step(call_uuid, "faq")
        await update_call_intent(call_log_id, "faq")

        info = (
            "We are open Tuesday through Sunday from 5 PM to 10 PM, "
            "closed on Mondays. We are located at 123 Main Street, downtown."
        )
        return Response(content=_menu_xml(host, info), media_type="application/xml")

    if digit == "3":
        await update_session_step(call_uuid, "transfer")
        await update_call_intent(call_log_id, "transfer", status="transferred")

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please hold while we connect you. Goodbye.</Speak>
    <Hangup/>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    await update_call_intent(call_log_id, "invalid")
    return Response(
        content=_menu_xml(host, "Invalid option, please try again."),
        media_type="application/xml",
    )


@router.post("/webhook/hangup")
@router.get("/webhook/hangup")
@router.post("/hangup")
@router.get("/hangup")
async def hangup(request: Request):
    p = await _params(request)
    call_uuid = p.get("CallUUID", "unknown")
    log.info("Call ended: %s", call_uuid)

    session = await get_session(call_uuid)
    if session:
        raw_id = session.get("call_log_id", "")
        call_log_id = int(raw_id) if raw_id else None

        duration = None
        started = session.get("started_at")
        if started:
            dt = datetime.fromisoformat(started)
            duration = int((datetime.now(timezone.utc) - dt).total_seconds())

        summary = None
        conv = _conversations.get(call_uuid)
        if conv and conv.reservation_complete:
            r = conv.reservation
            summary = (
                f"Reservation confirmed for {r.name} on {r.date} "
                f"at {r.time} for {r.party_size} people."
            )

        await finalize_call_log(call_log_id, duration, summary)
        await delete_session(call_uuid)

    conv = _conversations.pop(call_uuid, None)
    if conv and conv.reservation_complete and conv.caller_number:
        asyncio.create_task(send_reservation_sms(conv))

    return Response(content="OK", media_type="text/plain")
