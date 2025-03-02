"""
llm_handler.py — GPT-4o-mini Conversation Engine
==================================================
Drives the reservation dialogue by maintaining conversation history,
generating context-aware responses, and extracting structured reservation
data from the model output via inline JSON tags.
"""

import json
import logging

from openai import AsyncOpenAI

from utils.config import Config
from conversation_state import ConversationState

log = logging.getLogger(__name__)

AGENT_PROMPT = """You are a friendly reservation agent for Mario's Italian Kitchen, an upscale Italian restaurant. You are speaking to a customer on the phone. Your job is to help them make a reservation through a natural phone conversation.

Your goals:
1. Warmly greet callers
2. Collect: date, time, party size, and name for the reservation
3. Check availability against the available times provided in the context
4. Offer alternatives if requested time isn't available
5. Confirm all details before finalizing
6. Thank them and wish them a good day

IMPORTANT RULES:
- Keep responses SHORT (1-2 sentences max). This is a phone call, not a text chat.
- Be conversational, warm, and natural — like a real person on the phone.
- Ask for ONE piece of information at a time.
- If you don't understand something, politely ask the caller to repeat.
- When confirming, read back ALL details: date, time, party size, and name.
- After confirmation, say goodbye naturally.
- Never use markdown, bullet points, or formatting — this is spoken audio.
- Don't say "Great choice" or similar canned phrases repeatedly. Vary your language.

EXTRACTION INSTRUCTIONS:
When the caller provides information, extract it into a JSON block at the END
of your response using this exact format:

[EXTRACT]{"date": "...", "time": "...", "party_size": N, "name": "..."}[/EXTRACT]

Only include fields that were NEWLY provided in the caller's latest message.
Omit fields that weren't mentioned.  Example — caller only gave a date:
[EXTRACT]{"date": "this Saturday"}[/EXTRACT]

If the caller confirms the full reservation, include:
[EXTRACT]{"confirmed": true}[/EXTRACT]
"""


def _build_state_context(state: ConversationState) -> str:
    return (
        f"CURRENT RESERVATION STATE:\n"
        f"{state.get_state_summary()}\n\n"
        f"Continue the conversation naturally based on the above. "
        f"If the requested time is unavailable, suggest alternatives."
    )


def _split_extraction(raw_text: str) -> tuple[str, dict]:
    spoken = raw_text
    fields: dict = {}

    tag_open, tag_close = "[EXTRACT]", "[/EXTRACT]"
    if tag_open in raw_text and tag_close in raw_text:
        idx_start = raw_text.index(tag_open)
        idx_end = raw_text.index(tag_close)
        json_str = raw_text[idx_start + len(tag_open):idx_end]
        spoken = raw_text[:idx_start].strip()

        try:
            fields = json.loads(json_str)
        except json.JSONDecodeError:
            log.warning("Could not parse extraction JSON: %s", json_str)

    return spoken, fields


class LLMHandler:
    """Stateful wrapper around the OpenAI chat completions API."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self._client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

    async def get_greeting(self, state: ConversationState) -> str:
        return await self.get_response(state, is_greeting=True)

    async def get_response(
        self,
        state: ConversationState,
        caller_text: str = "",
        is_greeting: bool = False,
    ) -> str:
        msgs = [
            {"role": "system", "content": AGENT_PROMPT},
            {"role": "system", "content": _build_state_context(state)},
            *state.messages,
        ]

        if caller_text:
            msgs.append({"role": "user", "content": caller_text})
        elif is_greeting:
            msgs.append({
                "role": "user",
                "content": "(The customer just called. Greet them warmly.)",
            })

        try:
            completion = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                temperature=0.7,
                max_tokens=200,
            )

            raw = completion.choices[0].message.content.strip()
            log.info("[%s] LLM raw -> %s", self.call_id, raw)

            spoken, extracted = _split_extraction(raw)

            if "date" in extracted:
                state.reservation.date = extracted["date"]
                state.date_requested = True
            if "time" in extracted:
                state.reservation.time = extracted["time"]
                state.time_requested = True
            if "party_size" in extracted:
                state.reservation.party_size = extracted["party_size"]
                state.party_size_requested = True
            if "name" in extracted:
                state.reservation.name = extracted["name"]
                state.name_requested = True
            if extracted.get("confirmed"):
                state.reservation_complete = True

            state.update_from_assistant(spoken)

            if caller_text:
                state.add_message("user", caller_text)
            state.add_message("assistant", spoken)

            return spoken

        except Exception as exc:
            log.error("[%s] LLM call failed: %s", self.call_id, exc)
            return "I'm sorry, I'm having a little trouble right now. Could you say that again?"
