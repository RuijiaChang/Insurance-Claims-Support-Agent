import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop import engine
from app.sop.context import ResponderContext, assert_no_record_data, build_context
from app.sop.engine import decide
from app.sop.extraction import Extraction
from app.sop.memory import apply_extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, StepResult, TurnPlan
from app.sop.state import Message, SessionState
from tests.fakes import ex, make_ctx

MARGARET_ID: dict[str, str] = {
    "full_name": "Margaret Chen",
    "dob": "1985-03-15",
    "phone": "(650) 521-2836",
}
MARGARET_TEXT = (
    "Hi, I'm Margaret Chen, born March 15 1985, phone (650) 521-2836. "
    "My healthcare claim from January was denied, why?"
)
MARGARET_OPENER: dict[str, Any] = {
    "identity": MARGARET_ID,
    "case_hints": {"case_type": "healthcare", "status": "denied", "month": 1},
    "intent": "denial_question",
    "question": "Why was my claim denied?",
    "acts": ["provide_info", "ask_question"],
}
REP: dict[str, Any] = {
    "caller_role": "representative",
    "representative": {
        "rep_name": "David Chen",
        "relationship": "child",
        "policyholder_name": "Margaret Chen",
    },
}


def _turn(
    state: SessionState,
    repo: FixtureRepo,
    sop: SopConfig,
    extraction: Extraction,
    turn: int = 1,
    user_text: str = "",
    **ctx_kw: Any,
) -> tuple[TurnPlan, PolicyCtx]:
    """Mirror the pipeline: fold the extraction into memory, then decide."""
    apply_extraction(state, extraction, turn)
    ctx = make_ctx(repo, sop, turn=turn, user_text=user_text, **ctx_kw)
    return decide(state, extraction, ctx), ctx


def _kinds(plan: TurnPlan) -> list[str]:
    return [d.kind for d in plan.directives]


def _sop_with_hops(sop: SopConfig, max_hops: int) -> SopConfig:
    process = sop.process.model_copy(update={"max_hops": max_hops})
    return sop.model_copy(update={"process": process})


def _verified(phase: Phase, sub: SubState, case_id: str | None = None) -> SessionState:
    s = SessionState.new("s1")
    s.phase = phase
    s.sub_state = sub
    s.verified_party_id = "P9"
    s.access_granted = True
    if case_id is not None:
        s.active_case_id = case_id
        s.discussed_case_ids = [case_id]
    return s


# --- decide ---------------------------------------------------------------------


def test_margaret_opener_three_hops(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    plan, _ = _turn(state, repo, sop, ex(**MARGARET_OPENER), user_text=MARGARET_TEXT)

    assert plan.hops == [Phase.VERIFY_ID, Phase.RESOLVE_INTENT, Phase.PROCESS_CASE]
    kinds = _kinds(plan)
    for kind in ("confirm_verified", "case_selected", "answer_question"):
        assert kind in kinds
    order = [kinds.index(k) for k in ("confirm_verified", "case_selected", "answer_question")]
    assert order == sorted(order)
    assert state.phase == Phase.PROCESS_CASE and state.sub_state == SubState.ACTIVE
    assert state.active_case_id == "CL-2048"
    assert plan.fact_scope == "case"


def test_hop_limit_respected(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    plan, _ = _turn(state, repo, _sop_with_hops(sop, 2), ex(**MARGARET_OPENER))

    # Two handler calls: VERIFY_ID moved to RESOLVE_INTENT, RESOLVE_INTENT to PROCESS_CASE;
    # the PROCESS_CASE handler is not run, so the question is not answered this turn.
    assert plan.hops == [Phase.VERIFY_ID, Phase.RESOLVE_INTENT, Phase.PROCESS_CASE]
    assert "answer_question" not in _kinds(plan)
    assert state.phase == Phase.PROCESS_CASE


def test_hop_limit_caps_handler_calls(
    repo: FixtureRepo, sop: SopConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Phase] = []

    def ping(to: Phase, sub: SubState) -> Any:
        def handler(state: SessionState, extraction: Extraction, ctx: PolicyCtx) -> StepResult:
            calls.append(state.phase)
            return StepResult(
                directives=[Directive(kind="anything_else")],
                quick_replies=[],
                transition=(to, sub),
                continue_hop=True,
            )

        return handler

    monkeypatch.setitem(
        engine.HANDLERS, Phase.PROCESS_CASE, ping(Phase.RESOLVE_INTENT, SubState.NONE)
    )
    monkeypatch.setitem(
        engine.HANDLERS, Phase.RESOLVE_INTENT, ping(Phase.PROCESS_CASE, SubState.ACTIVE)
    )
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    plan, _ = _turn(state, repo, sop, ex())

    assert len(calls) == sop.process.max_hops == 3
    assert len(plan.directives) == 3
    assert plan.hops == [
        Phase.PROCESS_CASE,
        Phase.RESOLVE_INTENT,
        Phase.PROCESS_CASE,
        Phase.RESOLVE_INTENT,
    ]


def test_guard_extra_directives_come_first(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    extraction = ex(
        question="Why was it denied?",
        acts=["ask_question"],
        emotion={"label": "frustrated", "intensity": 1},
    )
    plan, _ = _turn(state, repo, sop, extraction, turn=3)

    kinds = _kinds(plan)
    assert kinds[0] == "empathize"
    assert "answer_question" in kinds
    assert plan.hops == [Phase.PROCESS_CASE]


def test_guard_extra_replies_used_when_hops_have_none(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    state.counters.negative_emotion_streak = 2
    extraction = ex(
        identity={"full_name": "Margaret Chen"}, emotion={"label": "angry", "intensity": 2}
    )
    plan, _ = _turn(state, repo, sop, extraction)

    assert "offer_handoff" in _kinds(plan)
    assert [q.action for q in plan.quick_replies] == ["handoff_accept"]


def test_last_hop_replies_win(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.RESOLVE_INTENT, SubState.NONE)
    plan, _ = _turn(state, repo, sop, ex(acts=["provide_info"]))

    assert plan.hops == [Phase.RESOLVE_INTENT]
    assert "no_hints" in _kinds(plan)
    assert all(q.action.startswith("select_case:") for q in plan.quick_replies)
    assert plan.fact_scope == "claims_summary"


def test_guard_stop_continue_hop_offers_email(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    plan, _ = _turn(state, repo, sop, ex(acts=["request_human"]), turn=4)

    assert plan.hops == [Phase.PROCESS_CASE, Phase.POST_PROCESS]
    assert _kinds(plan) == ["offer_email"]
    assert state.phase == Phase.POST_PROCESS and state.sub_state == SubState.OFFER
    assert state.pending_handoff == "user_request"
    assert {q.action for q in plan.quick_replies} == {"email_send", "email_skip"}


def test_guard_stop_unverified_handoff_ends_turn(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    plan, _ = _turn(state, repo, sop, ex(acts=["request_human"]))

    assert plan.hops == [Phase.VERIFY_ID, Phase.HANDOFF]
    assert _kinds(plan) == ["handoff_done"]
    assert state.phase == Phase.HANDOFF


@pytest.mark.parametrize("phase", [Phase.HANDOFF, Phase.CLOSED])
def test_terminal_phase_calls_no_handler(
    phase: Phase, repo: FixtureRepo, sop: SopConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(state: SessionState, extraction: Extraction, ctx: PolicyCtx) -> StepResult:
        raise AssertionError("handler called in a terminal phase")

    for p in list(engine.HANDLERS):
        monkeypatch.setitem(engine.HANDLERS, p, boom)
    state = _verified(phase, SubState.NONE)
    plan, _ = _turn(state, repo, sop, ex(acts=["ask_question"]))

    assert _kinds(plan) == ["session_closed"]
    assert plan.hops == [phase]
    assert state.phase == phase


def test_only_decide_calls_transition() -> None:
    app_dir = Path(engine.__file__).resolve().parents[1]
    call = re.compile(r"\btransition\s*\(")
    write = re.compile(r"\.phase\s*=(?!=)")
    callers: list[str] = []
    writers: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(app_dir).as_posix()
        if rel == "sop/phases.py":
            continue
        source = path.read_text(encoding="utf-8")
        if call.search(source):
            callers.append(rel)
        if write.search(source):
            writers.append(rel)
    assert callers == ["sop/engine.py"]
    assert writers == []


# --- build_context --------------------------------------------------------------


def _context(
    state: SessionState, plan: TurnPlan, ctx: PolicyCtx, user_text: str
) -> ResponderContext:
    return build_context(state, plan, ctx, user_text)


def test_context_before_access_has_no_records(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    text = "I'm Margaret Chen, born 1985-03-15. My denied healthcare claim from January."
    extraction = ex(
        identity={"full_name": "Margaret Chen", "dob": "1985-03-15"},
        case_hints={"case_type": "healthcare", "status": "denied", "month": 1},
    )
    plan, ctx = _turn(state, repo, sop, extraction, user_text=text)
    rc = _context(state, plan, ctx, text)

    blob = json.dumps(rc.facts)
    assert "CL-" not in blob and "1450" not in blob
    assert rc.facts["needed"] == 1
    assert set(rc.facts["options"]) == {"phone", "email", "id_last4"}
    assert rc.facts["user_hints"] == {"case_type": "healthcare", "status": "denied", "month": "1"}
    assert rc.tool_executor is None
    assert rc.phase == Phase.VERIFY_ID
    assert rc.directives == plan.directives
    assert text in rc.whitelist_text and blob in rc.whitelist_text


def test_context_consent_pending_has_no_records(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    plan, ctx = _turn(state, repo, sop, ex(identity=MARGARET_ID, **REP))
    assert state.sub_state == SubState.CONSENT_PENDING
    assert state.verified_party_id == "P9" and not state.access_granted

    # Even a plan asking for case facts gets only the pre-access facts.
    forced = TurnPlan(directives=plan.directives, quick_replies=[], fact_scope="case")
    for p in (plan, forced):
        rc = _context(state, p, ctx, "I'm David, her son")
        blob = json.dumps(rc.facts)
        assert "CL-" not in blob and "1450" not in blob
        for value in ("+16505212836", "margaret@email.com", "4472"):
            assert value not in blob
        assert set(rc.facts) == {"needed", "options", "user_hints"}
        assert rc.tool_executor is None


def test_context_claims_summary(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.RESOLVE_INTENT, SubState.NONE)
    plan, ctx = _turn(state, repo, sop, ex(acts=["provide_info"]))
    rc = _context(state, plan, ctx, "which claims do I have")

    assert len(rc.facts["claims"]) == len(repo.claims_for("P9"))
    assert rc.tool_executor is None


def test_context_case_facts_for_margaret(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    state.transcript.append(Message(role="user", text=MARGARET_TEXT, turn=1))
    plan, ctx = _turn(state, repo, sop, ex(**MARGARET_OPENER), user_text=MARGARET_TEXT)
    rc = _context(state, plan, ctx, MARGARET_TEXT)

    facts = rc.facts
    assert facts["claim"]["case_id"] == "CL-2048"
    assert "party_id" not in facts["claim"]
    assert "net_pay" in facts["field_definitions"]
    assert isinstance(facts["field_definitions"]["net_pay"], str)
    assert facts["deadline"] is not None and "deadline" in facts["deadline"]
    assert "per_document" in facts["doc_requirements"]
    assert facts["followup"]["kind"] in ("matched", "fallback", "no_specific_guidance")
    assert "alternatives" not in facts
    assert rc.tool_executor is not None
    assert "CL-2048" in rc.whitelist_text and MARGARET_TEXT in rc.whitelist_text


def test_context_case_includes_alternatives(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    plan, ctx = _turn(
        state, repo, sop, ex(acts=["cannot_obtain"], question="I can't get it"), turn=3
    )
    rc = _context(state, plan, ctx, "I can't get the itemized bill")

    assert isinstance(rc.facts["alternatives"], dict)


def test_context_tool_executor_runs_tools(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    plan, ctx = _turn(state, repo, sop, ex(acts=["ask_question"], question="what is net pay"))
    rc = _context(state, plan, ctx, "what is net pay")

    assert rc.tool_executor is not None
    out = rc.tool_executor("get_field_definition", {"field": "net_pay"})
    assert out["field"] == "net_pay" and out["definition"]


def test_context_email_scope(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _verified(Phase.PROCESS_CASE, SubState.ACTIVE, "CL-2048")
    _turn(state, repo, sop, ex(acts=["ask_question"], question="why denied"), turn=2)
    _turn(state, repo, sop, ex(acts=["done"]), turn=3)
    plan, ctx = _turn(state, repo, sop, ex(acts=["affirm"]), turn=4, action="email_send")
    assert plan.fact_scope == "email"
    rc = _context(state, plan, ctx, "yes")

    assert state.email.preview is not None
    assert rc.facts == {"draft": state.email.preview.model_dump()}
    assert rc.tool_executor is None


def test_context_history_last_six(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    for i in range(10):
        state.transcript.append(Message(role="user" if i % 2 else "agent", text=f"m{i}", turn=i))
    plan, ctx = _turn(state, repo, sop, ex())
    rc = _context(state, plan, ctx, "hello")

    assert [m.text for m in rc.history] == [f"m{i}" for i in range(4, 10)]
    assert "m1" in rc.whitelist_text and "m0" not in rc.whitelist_text


# --- assert_no_record_data ------------------------------------------------------


@pytest.mark.parametrize(
    "facts",
    [
        {"x": "CL-2048"},
        {"x": "call +16505212836"},
        {"x": "MARGARET@email.com"},
        {"x": "born 1985-03-15"},
        {"x": "ssn 4472"},
    ],
)
def test_assert_no_record_data_raises(facts: dict[str, Any], repo: FixtureRepo) -> None:
    with pytest.raises(AssertionError):
        assert_no_record_data(facts, repo)


def test_assert_no_record_data_allows_clean_facts(repo: FixtureRepo) -> None:
    assert_no_record_data({"needed": 1, "options": ["phone"], "n": "144720", "y": "A4472B"}, repo)


def test_assert_no_record_data_allows_callers_own_words(repo: FixtureRepo) -> None:
    facts = {"user_hints": {"case_quote": "about cl-2048, my email margaret@email.com"}}
    assert_no_record_data(facts, repo, "It's about CL-2048, my email margaret@email.com")
    with pytest.raises(AssertionError):
        assert_no_record_data(facts, repo, "something else")
