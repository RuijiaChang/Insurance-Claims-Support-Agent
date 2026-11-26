"""Human handoff policy (minimal: create the ticket and end in HANDOFF)."""

from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, StepResult
from app.sop.state import SessionState
from app.tools.handoff import HandoffReason, create_ticket


def start_handoff(state: SessionState, reason: HandoffReason, ctx: PolicyCtx) -> StepResult:
    ticket = create_ticket(
        reason,
        verified=state.verified_party_id is not None,
        access_granted=state.access_granted,
        stated_intent=state.memory.get("intent") or state.memory.get("case_quote"),
        active_case_id=state.active_case_id,
        turn=ctx.turn,
    )
    state.handoff = ticket
    return StepResult(
        directives=[Directive(kind="handoff_done", data={"ticket_id": ticket.ticket_id})],
        quick_replies=[],
        transition=(Phase.HANDOFF, SubState.NONE),
    )
