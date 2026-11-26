from typing import Any

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.extraction import Extraction
from app.sop.memory import apply_extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import StepResult
from app.sop.policies.resolve import handle_resolve
from app.sop.state import SessionState
from tests.fakes import apply_step, ex, make_ctx


def _state(party: str = "P9") -> SessionState:
    s = SessionState.new("s1")
    s.phase = Phase.RESOLVE_INTENT
    s.sub_state = SubState.NONE
    s.verified_party_id = party
    s.access_granted = True
    return s


def _remember(state: SessionState, **hints: Any) -> None:
    """Hints said during verification (phase VERIFY_ID)."""
    state.phase = Phase.VERIFY_ID
    apply_extraction(state, ex(case_hints=hints), 1)
    state.phase = Phase.RESOLVE_INTENT


def _turn(
    state: SessionState,
    repo: FixtureRepo,
    sop: SopConfig,
    extraction: Extraction | None = None,
    turn: int = 2,
    **ctx_kw: Any,
) -> StepResult:
    extraction = extraction or ex()
    apply_extraction(state, extraction, turn)
    step = handle_resolve(state, extraction, make_ctx(repo, sop, turn=turn, **ctx_kw))
    apply_step(state, step)
    return step


def test_margaret_memory_selects_cl2048_and_hops(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _remember(s, case_type="healthcare", status="denied", month=1)
    step = _turn(s, repo, sop)
    assert s.phase == Phase.PROCESS_CASE and s.sub_state == SubState.ACTIVE
    assert s.active_case_id == "CL-2048"
    assert s.discussed_case_ids == ["CL-2048"]
    assert s.primary_intent == "denial_question"
    assert s.memory.slots["case_type"].used_phase == Phase.RESOLVE_INTENT
    assert s.memory.slots["month"].used_phase == Phase.RESOLVE_INTENT
    assert step.continue_hop is True
    assert step.fact_scope == "case"
    assert [d.kind for d in step.directives] == ["case_selected"]
    assert step.directives[0].data["other_case_hint"] is True
    assert "CL-2048" not in step.directives[0].data["summary_line"]


def test_status_inquiry_for_non_denied(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, ex(case_hints={"case_type": "auto"}))
    assert s.active_case_id == "CL-2102"
    assert s.primary_intent == "status_inquiry"


def test_existing_primary_intent_kept(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.primary_intent = "document_help"
    _turn(s, repo, sop, ex(case_hints={"case_type": "auto"}))
    assert s.primary_intent == "document_help"


def test_ambiguous_quick_replies(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _remember(s, case_type="healthcare", month=1)
    step = _turn(s, repo, sop)
    assert s.phase == Phase.RESOLVE_INTENT and s.sub_state == SubState.AWAITING_CHOICE
    assert {q.action for q in step.quick_replies} == {"select_case:CL-2048", "select_case:CL-2011"}
    assert step.directives[0].kind == "choose_case"
    assert len(step.directives[0].data["options"]) == 2
    assert s.pending_question is not None
    assert s.pending_question.kind == "choose_case"
    assert set(s.pending_question.options) == {"CL-2048", "CL-2011"}
    assert step.fact_scope == "claims_summary"
    assert s.active_case_id is None
    assert s.memory.slots["case_type"].used_phase is None


def test_select_case_action(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _remember(s, case_type="healthcare", month=1)
    _turn(s, repo, sop)
    s.pending_question = None
    step = _turn(s, repo, sop, turn=3, action="select_case:CL-2011")
    assert s.active_case_id == "CL-2011"
    assert s.phase == Phase.PROCESS_CASE
    assert step.continue_hop is True
    assert s.primary_intent == "status_inquiry"


def test_switch_uses_only_turn_hints(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _remember(s, case_type="healthcare", status="denied", month=1)
    _turn(s, repo, sop, ex(case_hints={"case_type": "auto"}))
    assert s.active_case_id == "CL-2102"


def test_no_hints_lists_all(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop)
    assert step.directives[0].kind == "no_hints"
    assert len(step.quick_replies) == 4
    assert s.sub_state == SubState.AWAITING_CHOICE
    assert step.fact_scope == "claims_summary"


def test_no_match_adds_handoff(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(case_hints={"case_id": "CL-9999"}))
    assert step.directives[0].kind == "no_match"
    actions = [q.action for q in step.quick_replies]
    assert actions[-1] == "handoff_accept"
    assert len(actions) == 5
    assert s.sub_state == SubState.AWAITING_CHOICE


def test_no_claims_p7(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state("P7")
    step = _turn(s, repo, sop)
    assert step.directives[0].kind == "no_claims"
    assert [q.action for q in step.quick_replies] == ["handoff_accept", "end_session"]
    assert step.fact_scope == "none"


def test_no_claims_end_session_closes(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state("P7")
    step = _turn(s, repo, sop, action="end_session")
    assert s.phase == Phase.CLOSED
    assert [d.kind for d in step.directives] == ["closing"]


def test_done_goes_to_post(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(acts=["done"]))
    assert s.phase == Phase.POST_PROCESS and s.sub_state == SubState.OFFER
    assert step.continue_hop is True
    assert step.directives == []


def test_end_session_action_goes_to_post(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, action="end_session")
    assert s.phase == Phase.POST_PROCESS


def test_never_reads_other_party_claims(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(case_hints={"case_id": "CL-3001"}))
    assert s.active_case_id is None
    assert step.directives[0].kind == "no_match"
    assert all("CL-3001" not in q.action for q in step.quick_replies)
