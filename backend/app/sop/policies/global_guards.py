"""Global guards run before the phase handler, in a fixed order (spec §8.0).

1. terminal phase (HANDOFF / CLOSED): reply "session closed", touch nothing;
2. actions and human requests: end_session (VERIFY_ID sub-states the handler
   does not cover), continue (no-op), handoff_accept / request_human;
3. scope: out_of_scope is declined, never answered; in_scope_general is
   answered from the knowledge base only, then pulled back to the current step;
4. otherwise reset the consecutive off-topic count; small talk gets a directive;
5. emotion directives (spec §9).

A turn that also carries identity fields or case hints is treated as in scope,
so a mixed message is never declined.

Handoff offers only live for one turn: ``handoff_offer_reason`` is read and
cleared at the start of every turn (an offer made this turn sets it again), and
``counters.l3_offered`` is cleared once the turn after the offer is over, so an
ignored offer never colours a later handoff ticket or a later "no".

Guards never change phase themselves: any change is returned through
``GuardDecision.step.transition``.
"""

from dataclasses import dataclass, field

from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, QuickReply, StepResult
from app.sop.policies.emotion import emotion_directives, gate_for
from app.sop.policies.handoff import start_handoff
from app.sop.state import SessionState
from app.tools.claims import claim_summary_line
from app.tools.guidance import kb_general
from app.tools.handoff import HandoffReason

OFF_TOPIC_REPLIES = [
    QuickReply(label="Talk to a representative", action="handoff_accept"),
    QuickReply(label="Continue", action="continue"),
]
_GUARD_CLOSES = frozenset({SubState.COLLECTING, SubState.REP_CHECK, SubState.CONSENT_PENDING})
_SUB_STATE_REASONS: dict[SubState, HandoffReason] = {
    SubState.CONSENT_EXPIRED: "consent_expired",
    SubState.REP_DENIED: "rep_denied",
}


@dataclass
class GuardDecision:
    stop: bool
    step: StepResult | None = None
    extra: list[Directive] = field(default_factory=list)
    extra_replies: list[QuickReply] = field(default_factory=list)


def _stop(state: SessionState, step: StepResult) -> GuardDecision:
    # The emotion step, which consumes last turn's L3 offer, does not run this turn.
    state.counters.l3_offered.clear()
    return GuardDecision(stop=True, step=step)


def apply_global_guards(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> GuardDecision:
    # 1. Terminal phases: no state change at all.
    if state.phase in (Phase.HANDOFF, Phase.CLOSED):
        return _stop(
            state,
            StepResult(
                directives=[Directive(kind="session_closed", data={"phase": state.phase.value})],
                quick_replies=[],
            ),
        )

    # A handoff offer made last turn may be accepted now; otherwise it lapses.
    offer_reason = state.handoff_offer_reason
    state.handoff_offer_reason = None

    # 2. Actions and explicit human requests.
    if ctx.action == "end_session" and (
        state.phase == Phase.VERIFY_ID and state.sub_state in _GUARD_CLOSES
    ):
        state.pending_question = None
        return _stop(
            state,
            StepResult(
                directives=[Directive(kind="closing")],
                quick_replies=[],
                transition=(Phase.CLOSED, SubState.NONE),
            ),
        )
    if ctx.action == "handoff_accept" or "request_human" in ex.acts:
        reason = _handoff_reason(state, offer_reason)
        state.pending_question = None
        return _stop(state, start_handoff(state, reason, ctx))

    # 3. Scope. A turn carrying identity or case data is in scope whatever its label.
    has_claim_data = _has_claim_data(ex)
    if ex.scope == "out_of_scope" and not has_claim_data:
        return _stop(state, _decline_off_topic(state, ctx))

    # 4. Not off-topic: the consecutive run is broken.
    state.counters.off_topic_consecutive = 0
    extra: list[Directive] = []
    if ex.scope == "in_scope_general":
        answer = Directive(
            kind="answer_general",
            data={"kb": kb_general(ctx.repo), "question": ex.question or ctx.user_text},
        )
        if not has_claim_data:
            return _stop(
                state, StepResult(directives=[answer, *_pull_back(state, ctx)], quick_replies=[])
            )
        extra.append(answer)
    elif ex.scope == "small_talk":
        extra.append(Directive(kind="small_talk"))

    # 5. Emotion.
    emotion, replies = emotion_directives(state, ex, gate_for(state), ctx.sop.emotion)
    return GuardDecision(stop=False, extra=extra + emotion, extra_replies=replies)


def _handoff_reason(state: SessionState, offer_reason: HandoffReason | None) -> HandoffReason:
    if offer_reason is not None:
        return offer_reason
    if state.sub_state in _SUB_STATE_REASONS:
        return _SUB_STATE_REASONS[state.sub_state]
    if (
        state.phase == Phase.PROCESS_CASE
        and state.active_case_id is not None
        and state.active_case_id in state.alternatives_offered
    ):
        return "docs_exhausted"
    return "user_request"


def _has_claim_data(ex: Extraction) -> bool:
    identity = ex.identity.model_dump().values()
    hints = ex.case_hints
    return any(v is not None for v in identity) or (
        not hints.to_input().is_empty() or bool(hints.free_text and hints.free_text.strip())
    )


def _decline_off_topic(state: SessionState, ctx: PolicyCtx) -> StepResult:
    counters = state.counters
    counters.off_topic_total += 1
    counters.off_topic_consecutive += 1
    offer = counters.off_topic_total >= ctx.sop.scope.off_topic_offer_human_after
    if offer:
        state.handoff_offer_reason = "off_topic"
    return StepResult(
        directives=[Directive(kind="decline_off_topic", data={"offer_handoff": offer})],
        quick_replies=list(OFF_TOPIC_REPLIES) if offer else [],
    )


def _pull_back(state: SessionState, ctx: PolicyCtx) -> list[Directive]:
    """A directive that returns the caller to the step they were on."""
    if state.phase == Phase.VERIFY_ID:
        if state.sub_state != SubState.COLLECTING:
            return []
        identity = state.identity
        needed = max(0, ctx.sop.verification.min_matched_fields - identity.provided_count())
        return [
            Directive(
                kind="need_identity",
                data={"needed": needed, "options": list(identity.remaining_options())},
            )
        ]
    if state.phase == Phase.RESOLVE_INTENT:
        if not state.access_granted or state.verified_party_id is None:
            return []
        claims = ctx.repo.claims_for(state.verified_party_id)
        return [
            Directive(kind="choose_case", data={"options": [claim_summary_line(c) for c in claims]})
        ]
    if state.phase == Phase.PROCESS_CASE:
        return [Directive(kind="anything_else")]
    return []
