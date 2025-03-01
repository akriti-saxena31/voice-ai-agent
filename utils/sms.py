"""
utils/sms.py — SMS booking confirmation via Plivo
===================================================
Fires a single text message to the caller after a reservation is confirmed.
"""

import logging

import plivo

from utils.config import Config

log = logging.getLogger(__name__)

_plivo = plivo.RestClient(Config.PLIVO_AUTH_ID, Config.PLIVO_AUTH_TOKEN)


async def send_reservation_sms(conv) -> None:
    """Send an SMS recap of the confirmed reservation."""
    if not conv.caller_number or not conv.reservation_complete:
        return

    r = conv.reservation
    body = (
        f"Mario's Italian Kitchen — Reservation Confirmed!\n\n"
        f"Date: {r.date or 'N/A'}\n"
        f"Time: {r.time or 'N/A'}\n"
        f"Party size: {r.party_size or 'N/A'}\n"
        f"Name: {r.name or 'N/A'}\n\n"
        f"Thank you for choosing Mario's! We look forward to seeing you.\n"
        f"To modify or cancel, call us at {Config.PLIVO_NUMBER}"
    )

    try:
        _plivo.messages.create(
            src=Config.PLIVO_NUMBER,
            dst=conv.caller_number,
            text=body,
        )
        log.info("SMS sent to %s", conv.caller_number)
    except Exception as exc:
        log.error("SMS failed for %s: %s", conv.caller_number, exc)
