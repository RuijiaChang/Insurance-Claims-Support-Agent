"""RESOLVE_INTENT policy: pick the caller's claim from hints, remembered or fresh.

Claims come only from the verified party's own record. Handlers never change
phase themselves: they return ``StepResult.transition``.
"""

from app.data.repo import Claim
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, DirectiveKind, PolicyCtx, QuickReply, StepResult
from app.sop.state import PendingQuestion, SessionState
from app.tools.claims import CaseHintsInput, claim_summary_line, resolve_case

HANDOFF_REPLY = QuickReply(label="Talk to a representative", action="handoff_accept")
END_REPLY = QuickReply(label="End conversation", action="end_session")

_HINT_SLOTS = ("case_id", "case_type", "status", "month", "year")
SELECT_PREFIX = "select_case:"


def handle_resolve(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> StepResult:
    claims = ctx.repo.claims_for(state.verified_party_id) if state.verified_party_id else []
    wants_end = "done" in ex.acts or ctx.action == "end_session"

    if not claims:
        if wants_end:
            return StepResult(
                directives=[Directive(kind="closing")],
                quick_replies=[],
                transition=(Phase.CLOSED, SubState.NONE),
            )
        return StepResult(
            directives=[Directive(kind="no_claims")],
            quick_replies=[HANDOFF_REPLY, END_REPLY],
            fact_scope="none",
        )
    if wants_end:
        return StepResult(
            directives=[],
            quick_replies=[],
            transition=(Phase.POST_PROCESS, SubState.OFFER),
            continue_hop=True,
        )

    hints, from_memory = _hints(state, ex, ctx)
    outcome = resolve_case(claims, hints)

    if outcome.kind == "unique" and outcome.case is not None:
        return _selected(state, outcome.case, hints, from_memory, ctx.turn)
    if outcome.kind == "ambiguous":
        return _choose(state, "choose_case", outcome.candidates)
    if outcome.kind == "no_hints":
        return _choose(state, "no_hints", claims)
    return _choose(state, "no_match", claims, extra=[HANDOFF_REPLY])


def _hints(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> tuple[CaseHintsInput, bool]:
    """Return (hints, from_memory). This turn's hints win; memory is the fallback."""
    if ctx.action and ctx.action.startswith(SELECT_PREFIX):
        return CaseHintsInput(case_id=ctx.action[len(SELECT_PREFIX) :]), False
    turn_hints = ex.case_hints.to_input()
    if not turn_hints.is_empty():
        return turn_hints, False
    mem = state.memory
    return (
        CaseHintsInput(
            case_id=mem.get("case_id"),
            case_type=mem.get("case_type"),
            status=mem.get("status"),
            month=_to_int(mem.get("month")),
            year=_to_int(mem.get("year")),
        ),
        True,
    )


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _selected(
    state: SessionState, case: Claim, hints: CaseHintsInput, from_memory: bool, turn: int
) -> StepResult:
    state.active_case_id = case.case_id
    state.case_selected_turn = turn
    if case.case_id not in state.discussed_case_ids:
        state.discussed_case_ids.append(case.case_id)
    # Mark the memory slots the selection used: all remembered hints, or the slots
    # holding this turn's hints (memory stores every turn's hints before policy runs).
    for key in _HINT_SLOTS:
        value = getattr(hints, key)
        if from_memory or (value is not None and str(value) == state.memory.get(key)):
            state.memory.mark_used(key, Phase.RESOLVE_INTENT, turn)
    if not from_memory:
        # Picked with fresh hints: older hints described a different claim (e.g. the
        # denied January claim before "what about my auto claim?"), so retire them.
        for key in (*_HINT_SLOTS, "case_quote"):
            rec = state.memory.slots.get(key)
            if rec is not None and rec.captured_turn < turn:
                state.memory.drop(key)
    if state.primary_intent is None:
        state.primary_intent = "denial_question" if case.status == "denied" else "status_inquiry"
    state.pending_question = None
    return StepResult(
        directives=[
            Directive(
                kind="case_selected",
                data={"summary_line": claim_summary_line(case), "other_case_hint": True},
            )
        ],
        quick_replies=[],
        transition=(Phase.PROCESS_CASE, SubState.ACTIVE),
        continue_hop=True,
        fact_scope="case",
    )


def _choose(
    state: SessionState,
    kind: DirectiveKind,
    options: list[Claim],
    extra: list[QuickReply] | None = None,
) -> StepResult:
    state.pending_question = PendingQuestion(
        kind="choose_case", options=[c.case_id for c in options]
    )
    replies = [
        QuickReply(label=claim_summary_line(c), action=f"{SELECT_PREFIX}{c.case_id}")
        for c in options
    ]
    return StepResult(
        directives=[
            Directive(
                kind=kind,
                data={"options": [claim_summary_line(c) for c in options]},
            )
        ],
        quick_replies=replies + (extra or []),
        transition=(Phase.RESOLVE_INTENT, SubState.AWAITING_CHOICE),
        fact_scope="claims_summary",
    )
