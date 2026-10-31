"""Server-Sent Events helpers.

Event types: step | token | confirmation | message | done | error. `token` events replay the
finished reply in small chunks (the reply arrives as one structured-output object, so the typing
effect is a replay; `step` events are live). Concatenating all `token` texts gives `message`.
"""

import json
import re
from typing import Any

from fastapi.sse import format_sse_event

KEEPALIVE_SECONDS = 15  # proxies close idle connections; a comment line keeps it open
_WORD = re.compile(r"\S+\s*")

# Friendly progress text per graph node, shown while that node runs.
STEP_LABELS = {
    "supervisor": "Understanding your request…",
    "medical_rag": "Searching the knowledge base…",
    "doctor_finder": "Looking for suitable doctors…",
    "booking": "Checking availability…",
    "book_appointment": "Booking your appointment…",
    "cancel": "Looking up your appointments…",
    "cancel_appointment": "Cancelling your appointment…",
    "nearby_clinics": "Looking up clinics on OpenStreetMap…",
}


def sse(event: str, data: dict[str, Any]) -> bytes:
    return format_sse_event(event=event, data_str=json.dumps(data, ensure_ascii=False))


def keepalive() -> bytes:
    return format_sse_event(comment="keepalive")


def chunk_text(text: str, words_per_chunk: int = 3) -> list[str]:
    """Split into chunks of a few words, keeping all whitespace: ''.join(chunks) == text."""
    words = _WORD.findall(text)
    chunks = [
        "".join(words[i : i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)
    ]
    leading = text[: len(text) - len(text.lstrip())]
    if leading and chunks:
        chunks[0] = leading + chunks[0]
    return chunks
