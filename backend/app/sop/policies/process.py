"""PROCESS_CASE policy: answer follow-ups grounded only in claim and guidance data.

Every answer is logged to ``case_log`` for the email summary. Handlers never
change phase themselves: they return ``StepResult.transition``.
"""

from typing import Literal

from app.data.repo import Claim
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, StepResult
from app.sop.policies.resolve import HANDOFF_REPLY, SELECT_PREFIX
from app.sop.state import CaseLogEntry, PendingQuestion, SessionState
from app.tools.guidance import (
    FollowupResult,
    GuidanceTopic,
    Intent,
    deadline_fact,
    docs_exhausted_text,
    document_alternatives,
    documents_phrase,
    match_followup,
)

LogKind = Literal["fact", "next_step", "deadline"]

ALTERNATIVES_TOPIC: GuidanceTopic = "missing_required_material_alternatives"
# Intents the case record itself can answer even without specific guidance.
_CASE_FIELD_INTENTS: frozenset[Intent] = frozenset(
    {"status_inquiry", "payment_question", "denial_question"}
)


def handle_process(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> StepResult:
    case = _active_case(state, ctx)
    if case is None or _wants_switch(state, ex, ctx, case):
        return StepResult(
            directives=[],
            quick_replies=[],
            transition=(Phase.RESOLVE_INTENT, SubState.NONE),
            continue_hop=True,
        )
    if _wants_done(state, ex, ctx):
        return StepResult(
            directives=[],
            quick_replies=[],
            transition=(Phase.POST_PROCESS, SubState.OFFER),
            continue_hop=True,
        )

    question = ex.question or ctx.user_text
    if "cannot_obtain" in ex.acts:
        if case.case_id in state.alternatives_offered:
            return _docs_exhausted(ctx)
        state.alternatives_offered.append(case.case_id)
        # The alternatives topic has no keywords; force it rather than letting
        # an incidental phrase in the question pick another topic.
        followup = match_followup(ctx.repo, case, "", state.turn_intent, ALTERNATIVES_TOPIC)
        alternatives = document_alternatives(
            ctx.repo, case, None, ctx.sop.process.doc_fuzzy_threshold
        )
        return _answer(state, ctx, case, question, followup, alternatives, None)

    followup = match_followup(ctx.repo, case, question, state.turn_intent, ex.guidance_topic)
    return _answer(state, ctx, case, question, followup, None, ex.guidance_topic)


def _active_case(state: SessionState, ctx: PolicyCtx) -> Claim | None:
    if not state.verified_party_id or not state.active_case_id:
        return None
    for claim in ctx.repo.claims_for(state.verified_party_id):
        if claim.case_id == state.active_case_id:
            return claim
    return None


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _wants_switch(state: SessionState, ex: Extraction, ctx: PolicyCtx, case: Claim) -> bool:
    if state.case_selected_turn == ctx.turn:
        # RESOLVE just picked this case from this very extraction: answer, don't bounce.
        return False
    if "select_case" in ex.acts:
        return True
    action = ctx.action or ""
    if action.startswith(SELECT_PREFIX) and not _same(action[len(SELECT_PREFIX) :], case.case_id):
        return True
    hints = ex.case_hints.to_input()
    if hints.case_id is not None and not _same(hints.case_id, case.case_id):
        return True
    return hints.case_type is not None and not _same(hints.case_type, case.case_type)


def _wants_done(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> bool:
    pending = state.pending_question
    return (
        "done" in ex.acts
        or ("deny" in ex.acts and pending is not None and pending.kind == "anything_else")
        or ctx.action == "end_session"
    )


def _docs_exhausted(ctx: PolicyCtx) -> StepResult:
    return StepResult(
        directives=[
            Directive(kind="docs_exhausted", data={"text": docs_exhausted_text(ctx.repo)}),
            Directive(kind="offer_handoff", data={"reason": "process"}),
        ],
        quick_replies=[HANDOFF_REPLY],
        fact_scope="case",
    )


def _answer(
    state: SessionState,
    ctx: PolicyCtx,
    case: Claim,
    question: str,
    followup: FollowupResult,
    alternatives: dict[str, str] | None,
    asked_topic: GuidanceTopic | None,
) -> StepResult:
    data: dict[str, object] = {
        "question": question,
        "followup": {"kind": followup.kind, "topic": followup.topic, "text": followup.text},
    }
    if alternatives is not None:
        data["alternatives"] = alternatives
    directives = [Directive(kind="answer_question", data=data)]
    offer_handoff = False

    deadline = deadline_fact(case, ctx.today)
    if deadline is not None and deadline.passed:
        directives.append(
            Directive(kind="deadline_passed", data={"deadline": deadline.deadline.isoformat()})
        )
        offer_handoff = True
    # The record itself answers status/payment/denial questions; anything else, or a
    # guidance-type question (a topic was asked) that has no guidance here, gets no_data.
    if followup.kind == "no_specific_guidance" and (
        state.turn_intent not in _CASE_FIELD_INTENTS or asked_topic is not None
    ):
        directives.append(Directive(kind="no_data"))
        offer_handoff = True
    directives.append(Directive(kind="anything_else"))

    _log_answer(state, case, followup)
    state.pending_question = PendingQuestion(kind="anything_else")
    return StepResult(
        directives=directives,
        quick_replies=[HANDOFF_REPLY] if offer_handoff else [],
        fact_scope="case",
    )


def _log_answer(state: SessionState, case: Claim, followup: FollowupResult) -> None:
    cid = case.case_id
    _log(state, cid, "fact", f"Status: {case.status} — {case.summary}")
    if case.denial_reason:
        _log(state, cid, "fact", f"Denial reason: {case.denial_reason}")
    if case.documents_needed:
        _log(state, cid, "next_step", f"Submit {documents_phrase(case.documents_needed)}")
    if case.appeal_deadline is not None:
        _log(state, cid, "deadline", f"Appeal deadline: {case.appeal_deadline.isoformat()}")
    if followup.kind == "matched" and followup.text:
        _log(state, cid, "next_step", followup.text)


def _log(state: SessionState, case_id: str, kind: LogKind, text: str) -> None:
    entry = CaseLogEntry(case_id=case_id, kind=kind, text=text)
    if entry not in state.case_log:
        state.case_log.append(entry)
