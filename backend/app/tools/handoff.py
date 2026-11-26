"""Human handoff tickets."""

import secrets
from typing import Literal

from pydantic import BaseModel

HandoffReason = Literal[
    "user_request",
    "locked",
    "emotion",
    "off_topic",
    "consent_expired",
    "rep_denied",
    "docs_exhausted",
    "deadline_passed",
    "no_data",
]


class HandoffTicket(BaseModel):
    ticket_id: str
    reason: HandoffReason
    verified: bool
    stated_intent: str | None
    case_id: str | None
    created_turn: int


def create_ticket(
    reason: HandoffReason,
    verified: bool,
    access_granted: bool,
    stated_intent: str | None,
    active_case_id: str | None,
    turn: int,
) -> HandoffTicket:
    return HandoffTicket(
        ticket_id="HT-" + secrets.token_hex(3),
        reason=reason,
        verified=verified,
        stated_intent=stated_intent,
        case_id=active_case_id if access_granted else None,
        created_turn=turn,
    )
