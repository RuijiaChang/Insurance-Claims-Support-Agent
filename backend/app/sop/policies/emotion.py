"""Tiered emotion handling (spec §9).

L1 empathize -> L2 empathize + persuade (explain why, offer alternatives) ->
L3 stop persuading and offer a human. Once the L3 offer is declined, each turn
only restates the gate's requirement and keeps the handoff quick reply.

No emotion ever changes a gate or causes a disclosure: this module only adds
directives and updates counters.
"""

from app.settings import EmotionConfig
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, QuickReply
from app.sop.state import Gate, SessionState

HANDOFF_REPLY = QuickReply(label="Talk to a representative", action="handoff_accept")

_VERIFY_SUBS = frozenset({SubState.COLLECTING, SubState.LOCKED})
_CONSENT_SUBS = frozenset({SubState.CONSENT_PENDING, SubState.CONSENT_EXPIRED})


def gate_for(state: SessionState) -> Gate | None:
    """The gate the caller is currently held at, if any."""
    if state.phase == Phase.VERIFY_ID:
        if state.sub_state in _VERIFY_SUBS:
            return "verify"
        if state.sub_state in _CONSENT_SUBS:
            return "consent"
        return None
    if state.phase == Phase.POST_PROCESS:
        return "email_address"
    return None


def emotion_directives(
    state: SessionState, ex: Extraction, gate: Gate | None, cfg: EmotionConfig
) -> tuple[list[Directive], list[QuickReply]]:
    counters = state.counters
    label = ex.emotion.label
    intensity = ex.emotion.intensity
    negative = label != "neutral" and intensity >= 1
    counters.negative_emotion_streak = counters.negative_emotion_streak + 1 if negative else 0

    # Without a gate the L3 bookkeeping is kept under "verify" (controller ruling).
    key: Gate = gate or "verify"
    if counters.l3_offered.get(key) and "deny" in ex.acts:
        counters.l3_declined[key] = True

    declined = bool(counters.l3_declined.get(key))
    if declined and gate is not None:
        return [Directive(kind="restate_requirement", data={"gate": gate})], [HANDOFF_REPLY]

    refused = "refuse_info" in ex.acts or "bypass_attempt" in ex.acts or bool(ex.refused_fields)
    attempts = counters.persuasion_attempts.get(gate, 0) if gate is not None else 0
    l3 = (
        (gate is not None and attempts >= cfg.persuasion_budget and refused)
        or (counters.negative_emotion_streak >= cfg.escalate_streak and intensity >= 2)
        or (label == "angry" and intensity == 3)  # treated as abuse
    )
    if l3 and not declined:
        counters.l3_offered[key] = True
        state.handoff_offer_reason = "emotion"
        return (
            [
                Directive(kind="stop_persuading"),
                Directive(kind="offer_handoff", data={"reason": "emotion"}),
            ],
            [HANDOFF_REPLY],
        )

    if gate is not None and (intensity >= 2 or refused):
        counters.persuasion_attempts[gate] = attempts + 1
        shown = label if label != "neutral" else "frustrated"
        return (
            [
                Directive(kind="empathize", data={"label": shown}),
                Directive(kind="persuade", data={"gate": gate}),
            ],
            [],
        )

    if negative:
        return [Directive(kind="empathize", data={"label": label})], []
    return [], []
