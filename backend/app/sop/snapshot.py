"""Public session snapshot for the UI inspector.

Built field by field (never a dump of ``SessionState``) so nothing private slips
through: no identity values, no comparison fingerprint, no transcript, and before
access is granted no field-level match result (identity shows only
pending / provided / refused).
"""

from typing import Any

from app.sop.state import SessionState
from app.tools.identity import IDENTITY_FIELDS

EVENTS_SHOWN = 50


def _identity(state: SessionState) -> list[dict[str, str]]:
    matched = set(state.identity.matched_fields) if state.access_granted else set()
    return [
        {
            "field": f,
            "status": "matched" if f in matched else state.identity.fields[f].status,
        }
        for f in IDENTITY_FIELDS
    ]


def public_snapshot(state: SessionState) -> dict[str, Any]:
    emotion = state.last_emotion
    preview = state.email.preview
    return {
        "phase": state.phase.value,
        "sub_state": state.sub_state.value,
        "access_granted": state.access_granted,
        "caller_role": state.caller.role,
        "verification_failures": state.verification_failures,
        "identity": _identity(state),
        "memory": [
            {
                "key": key,
                "value": rec.value,
                "captured_phase": rec.captured_phase.value,
                "used_phase": rec.used_phase.value if rec.used_phase is not None else None,
            }
            for key, rec in state.memory.slots.items()
        ],
        "active_case_id": state.active_case_id,
        "discussed_case_ids": list(state.discussed_case_ids),
        "primary_intent": state.primary_intent,
        "emotion": {"label": emotion[0], "intensity": emotion[1]} if emotion else None,
        "counters": state.counters.model_dump(mode="json"),
        "consent": {
            "status": state.consent.status,
            "polls": state.consent.polls,
            "scenario": state.consent.scenario,
        },
        "email": {
            "decision": state.email.decision,
            "preview": preview.model_dump(mode="json") if preview is not None else None,
        },
        "handoff": state.handoff.model_dump(mode="json") if state.handoff is not None else None,
        "events": [
            {"turn": e.turn, "stage": e.stage, "summary": e.summary}
            for e in state.events[-EVENTS_SHOWN:]
        ],
    }
