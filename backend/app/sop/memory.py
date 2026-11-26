"""Cross-phase memory: fold each turn's extraction into session state."""

from app.sop.extraction import Extraction
from app.sop.phases import Phase
from app.sop.state import SessionState
from app.tools.identity import IDENTITY_FIELDS


def apply_extraction(state: SessionState, ex: Extraction, turn: int) -> None:
    phase = state.phase

    if state.verified_party_id is None:
        for field in IDENTITY_FIELDS:
            value = getattr(ex.identity, field)
            if value:
                state.identity.add(field, value, turn)
        if ex.identity.policy_number:
            state.identity.policy_number = ex.identity.policy_number
        for field in ex.refused_fields:
            state.identity.refuse(field, turn)

    if phase == Phase.VERIFY_ID:
        if ex.caller_role != "unknown":
            state.caller.role = ex.caller_role
        rep = ex.representative
        if rep is not None:
            if rep.rep_name:
                state.caller.rep_name = rep.rep_name
            if rep.relationship:
                state.caller.relationship = rep.relationship
            if rep.policyholder_name:
                state.caller.policyholder_name = rep.policyholder_name

    hints = ex.case_hints
    slots: dict[str, str | int | None] = {
        "case_id": hints.case_id,
        "case_type": hints.case_type,
        "status": hints.status,
        "month": hints.month,
        "year": hints.year,
        "case_quote": hints.free_text,
        "intent": ex.intent,
        "email_preference": ex.email_preference,
    }
    for key, value in slots.items():
        if value is not None and str(value).strip():
            state.memory.set(key, str(value), turn, phase)

    state.turn_intent = ex.intent
    if ex.intent is not None and (state.primary_intent is None or "select_case" in ex.acts):
        state.primary_intent = ex.intent
    state.last_emotion = (ex.emotion.label, ex.emotion.intensity)
