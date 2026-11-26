"""Conversation phases, sub-states and the only legal way to change phase."""

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sop.state import SessionState


class Phase(StrEnum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    HANDOFF = "HANDOFF"  # terminal: handed to a human
    CLOSED = "CLOSED"  # terminal: session ended


class SubState(StrEnum):
    NONE = "NONE"
    COLLECTING = "COLLECTING"
    REP_CHECK = "REP_CHECK"
    REP_DENIED = "REP_DENIED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    LOCKED = "LOCKED"
    AWAITING_CHOICE = "AWAITING_CHOICE"
    ACTIVE = "ACTIVE"
    OFFER = "OFFER"
    PREVIEW = "PREVIEW"
    SENT = "SENT"
    SKIPPED = "SKIPPED"


ALLOWED: dict[Phase, frozenset[Phase]] = {
    Phase.VERIFY_ID: frozenset({Phase.RESOLVE_INTENT, Phase.HANDOFF, Phase.CLOSED}),
    Phase.RESOLVE_INTENT: frozenset(
        {Phase.PROCESS_CASE, Phase.POST_PROCESS, Phase.HANDOFF, Phase.CLOSED}
    ),
    Phase.PROCESS_CASE: frozenset({Phase.RESOLVE_INTENT, Phase.POST_PROCESS, Phase.HANDOFF}),
    Phase.POST_PROCESS: frozenset({Phase.PROCESS_CASE, Phase.CLOSED, Phase.HANDOFF}),
    Phase.HANDOFF: frozenset(),
    Phase.CLOSED: frozenset(),
}


class IllegalTransition(Exception):
    pass


def transition(state: "SessionState", to: Phase, sub: SubState) -> None:
    """Move to (to, sub). Same phase only changes sub_state; cross-phase must be allowed."""
    if to != state.phase and to not in ALLOWED[state.phase]:
        raise IllegalTransition(f"{state.phase}->{to}")
    state.phase = to
    state.sub_state = sub
