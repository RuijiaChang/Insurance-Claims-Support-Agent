"""PolicyEngine: turn one extraction into a TurnPlan, hopping across phases.

``decide`` is the only caller of ``phases.transition`` in the application
(invariant I1): guards and phase handlers only *return* a transition, and the
LLM never changes phase. One user message may satisfy several phases at once
(e.g. full identity plus a case hint), so after a transition the new phase's
handler runs on the same extraction, up to ``sop.process.max_hops`` handler
calls per turn.
"""

from collections.abc import Callable

from app.sop import phases
from app.sop.extraction import Extraction
from app.sop.phases import Phase
from app.sop.plan import Directive, FactScope, PolicyCtx, QuickReply, StepResult, TurnPlan
from app.sop.policies.global_guards import apply_global_guards
from app.sop.policies.post import handle_post
from app.sop.policies.process import handle_process
from app.sop.policies.resolve import handle_resolve
from app.sop.policies.verify import handle_verify
from app.sop.state import SessionState

Handler = Callable[[SessionState, Extraction, PolicyCtx], StepResult]

HANDLERS: dict[Phase, Handler] = {
    Phase.VERIFY_ID: handle_verify,
    Phase.RESOLVE_INTENT: handle_resolve,
    Phase.PROCESS_CASE: handle_process,
    Phase.POST_PROCESS: handle_post,
}
_TERMINAL = frozenset({Phase.HANDOFF, Phase.CLOSED})


def _apply(state: SessionState, step: StepResult, hops: list[Phase]) -> bool:
    """Apply the step's transition; return True if the phase changed."""
    if step.transition is None:
        return False
    before = state.phase
    phases.transition(state, *step.transition)
    if state.phase != before:
        hops.append(state.phase)
        return True
    return False


def decide(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> TurnPlan:
    hops: list[Phase] = [state.phase]
    directives: list[Directive] = []
    replies: list[QuickReply] = []
    scope: FactScope = "none"

    guard = apply_global_guards(state, ex, ctx)
    if guard.stop:
        assert guard.step is not None
        step = guard.step
        directives = list(step.directives)
        replies = list(step.quick_replies)
        scope = step.fact_scope
        _apply(state, step, hops)
        if not (step.continue_hop and step.transition is not None):
            return TurnPlan(directives, replies, scope, hops)
        if state.phase in _TERMINAL:
            return TurnPlan(directives, replies, scope, hops)
    else:
        directives = list(guard.extra)

    for _ in range(ctx.sop.process.max_hops):
        if state.phase in _TERMINAL:
            break
        step = HANDLERS[state.phase](state, ex, ctx)
        directives.extend(step.directives)
        if step.quick_replies:
            replies = list(step.quick_replies)
        scope = step.fact_scope
        changed = _apply(state, step, hops)
        if not (step.continue_hop and changed):
            break

    if not replies:
        replies = list(guard.extra_replies)
    return TurnPlan(directives, replies, scope, hops)
