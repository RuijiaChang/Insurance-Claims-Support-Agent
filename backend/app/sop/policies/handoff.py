"""Human handoff policy (spec §8.6 rules table).

A caller with access gets the email-summary offer first: ``pending_handoff`` is
set and the turn hops to POST_PROCESS, whose handler hands off once the caller
sends or skips the email. Everyone else is handed off at once. Handlers never
change phase themselves: they return ``StepResult.transition``.
"""

from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, StepResult
from app.sop.state import SessionState
from app.tools.handoff import HandoffReason, create_ticket


def start_handoff(state: SessionState, reason: HandoffReason, ctx: PolicyCtx) -> StepResult:
    immediate = (
        not state.access_granted
        or reason == "locked"
        or state.phase == Phase.POST_PROCESS
        or state.email.decision is not None
    )
    if not immediate:
        state.pending_handoff = reason
        return StepResult(
            directives=[],
            quick_replies=[],
            transition=(Phase.POST_PROCESS, SubState.OFFER),
            continue_hop=True,
        )

    ticket = create_ticket(
        reason,
        verified=state.verified_party_id is not None,
        access_granted=state.access_granted,
        stated_intent=state.memory.get("intent") or state.memory.get("case_quote"),
        active_case_id=state.active_case_id,
        turn=ctx.turn,
    )
    state.handoff = ticket
    state.pending_handoff = None
    return StepResult(
        directives=[Directive(kind="handoff_done", data={"ticket_id": ticket.ticket_id})],
        quick_replies=[],
        transition=(Phase.HANDOFF, SubState.NONE),
    )
