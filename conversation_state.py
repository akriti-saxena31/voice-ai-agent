"""
conversation_state.py — Reservation State Machine
===================================================
Tracks what information has been collected, which phase the dialogue
is in, and what time slots are (randomly) available for the demo.
"""

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

DINNER_SLOTS = [
    "5:30 PM", "6:00 PM", "6:45 PM",
    "7:30 PM", "8:00 PM", "8:30 PM", "9:00 PM",
]


class ConversationPhase(str, Enum):
    GREETING = "greeting"
    COLLECTING_DATE = "collecting_date"
    COLLECTING_TIME = "collecting_time"
    COLLECTING_PARTY_SIZE = "collecting_party_size"
    COLLECTING_NAME = "collecting_name"
    CONFIRMING = "confirming"
    COMPLETED = "completed"


@dataclass
class ReservationDetails:
    date: str | None = None
    time: str | None = None
    party_size: int | None = None
    name: str | None = None


@dataclass
class ConversationState:
    """Mutable object shared across the STT/LLM/TTS pipeline for one call."""

    call_id: str = ""
    phase: ConversationPhase = ConversationPhase.GREETING
    reservation: ReservationDetails = field(default_factory=ReservationDetails)

    date_requested: bool = False
    time_requested: bool = False
    party_size_requested: bool = False
    name_requested: bool = False
    reservation_complete: bool = False

    messages: list[dict] = field(default_factory=list)
    _blocked_slots: list[str] = field(default_factory=list)

    # Caller metadata — set by plivo_webhook when the call arrives
    caller_number: Optional[str] = None
    call_log_id: Optional[int] = None

    def __post_init__(self):
        k = random.randint(2, 3)
        self._blocked_slots = random.sample(DINNER_SLOTS, k)

    def available_times(self) -> list[str]:
        return [s for s in DINNER_SLOTS if s not in self._blocked_slots]

    def is_time_open(self, requested: str) -> bool:
        norm = requested.strip().upper().replace(" ", "")
        return all(
            slot.upper().replace(" ", "") not in norm
            for slot in self._blocked_slots
        )

    def update_from_assistant(self, _response: str):
        r = self.reservation
        if r.date and r.time and r.party_size and r.name:
            self.phase = (
                ConversationPhase.COMPLETED if self.reservation_complete
                else ConversationPhase.CONFIRMING
            )
        elif r.date and r.time and r.party_size:
            self.phase = ConversationPhase.COLLECTING_NAME
        elif r.date and r.time:
            self.phase = ConversationPhase.COLLECTING_PARTY_SIZE
        elif r.date:
            self.phase = ConversationPhase.COLLECTING_TIME
        else:
            self.phase = ConversationPhase.COLLECTING_DATE

    def get_state_summary(self) -> str:
        r = self.reservation
        return "\n".join([
            f"Phase: {self.phase.value}",
            f"Date: {r.date or 'NOT YET COLLECTED'}",
            f"Time: {r.time or 'NOT YET COLLECTED'}",
            f"Party size: {r.party_size or 'NOT YET COLLECTED'}",
            f"Name: {r.name or 'NOT YET COLLECTED'}",
            f"Available times: {', '.join(self.available_times())}",
            f"Blocked times: {', '.join(self._blocked_slots)}",
            f"Reservation complete: {self.reservation_complete}",
        ])

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        log.info("[%s] %s: %s", self.call_id, role, content)
