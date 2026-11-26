"""Simulated consent flow (scripted poll sequences)."""

import secrets
from typing import Literal

from pydantic import BaseModel

ConsentStatus = Literal["not_requested", "pending", "approved", "expired"]


class ConsentState(BaseModel):
    scenario: str = "default"
    status: ConsentStatus = "not_requested"
    polls: int = 0
    resends: int = 0
    request_id: str | None = None


def request_consent(c: ConsentState) -> ConsentState:
    return c.model_copy(
        update={
            "status": "pending",
            "polls": 0,
            "request_id": "CR-" + secrets.token_hex(3),
        }
    )


def poll_consent(c: ConsentState, sequences: dict[str, list[str]]) -> ConsentState:
    if c.status != "pending":
        return c
    sequence = sequences.get(c.scenario) or sequences["default"]
    polls = c.polls + 1
    current = sequence[min(polls, len(sequence)) - 1]
    status: ConsentStatus
    if current == "approved":
        status = "approved"
    elif polls >= len(sequence):
        status = "expired"
    else:
        status = "pending"
    return c.model_copy(update={"polls": polls, "status": status})


def resend_consent(c: ConsentState, max_resends: int) -> ConsentState | None:
    if c.resends >= max_resends:
        return None
    return c.model_copy(update={"status": "pending", "polls": 0, "resends": c.resends + 1})
