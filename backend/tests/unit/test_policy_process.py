from datetime import date
from typing import Any

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.extraction import Extraction
from app.sop.memory import apply_extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import StepResult
from app.sop.policies.process import handle_process
from app.sop.state import PendingQuestion, SessionState
from app.tools.guidance import docs_exhausted_text
from tests.fakes import apply_step, ex, make_ctx


def _state(case_id: str = "CL-2048") -> SessionState:
    s = SessionState.new("s1")
    s.phase = Phase.PROCESS_CASE
    s.sub_state = SubState.ACTIVE
    s.verified_party_id = "P9"
    s.access_granted = True
    s.active_case_id = case_id
    s.discussed_case_ids = [case_id]
    return s


def _turn(
    state: SessionState,
    repo: FixtureRepo,
    sop: SopConfig,
    extraction: Extraction | None = None,
    turn: int = 3,
    **ctx_kw: Any,
) -> StepResult:
    extraction = extraction or ex()
    apply_extraction(state, extraction, turn)
    step = handle_process(state, extraction, make_ctx(repo, sop, turn=turn, **ctx_kw))
    apply_step(state, step)
    return step


def _kinds(step: StepResult) -> list[str]:
    return [d.kind for d in step.directives]


def _log(state: SessionState) -> list[tuple[str, str, str]]:
    return [(e.case_id, e.kind, e.text) for e in state.case_log]


def test_answer_denial_logs_facts(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(
        s,
        repo,
        sop,
        ex(intent="denial_question", question="why was my claim denied?", acts=["ask_question"]),
    )
    assert _kinds(step) == ["answer_question", "anything_else"]
    assert step.fact_scope == "case"
    assert step.transition is None
    answer = step.directives[0].data
    assert answer["question"] == "why was my claim denied?"
    assert set(answer["followup"]) == {"kind", "topic", "text"}
    assert s.pending_question == PendingQuestion(kind="anything_else")
    log = _log(s)
    assert (
        "CL-2048",
        "fact",
        "Status: denied — Healthcare claim denied due to missing pathology report and office note",
    ) in log
    assert any(k == "fact" and t.startswith("Denial reason: ") for _, k, t in log)
    assert ("CL-2048", "next_step", "Submit the pathology report and the office note") in log
    assert ("CL-2048", "deadline", "Appeal deadline: 2026-03-18") in log
    assert "deadline_passed" not in _kinds(step)


def test_case_log_dedupes_repeat_answers(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    q = ex(intent="denial_question", question="why was it denied?")
    _turn(s, repo, sop, q)
    before = len(s.case_log)
    _turn(s, repo, sop, q, turn=4)
    assert len(s.case_log) == before


def test_matched_followup_logged_as_next_step(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(intent="document_submission", question="how do i submit?"))
    followup = step.directives[0].data["followup"]
    assert followup["kind"] == "matched"
    assert followup["topic"] == "submission_method"
    assert ("CL-2048", "next_step", followup["text"]) in _log(s)


def test_question_falls_back_to_user_text(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(intent="next_steps"), user_text="how do i submit?")
    assert step.directives[0].data["question"] == "how do i submit?"
    assert step.directives[0].data["followup"]["topic"] == "submission_method"


def test_deadline_passed_directive(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(
        s,
        repo,
        sop,
        ex(intent="denial_question", question="can I still appeal?"),
        today=date(2026, 11, 25),
    )
    kinds = _kinds(step)
    assert kinds[0] == "answer_question"
    assert "deadline_passed" in kinds
    assert kinds[-1] == "anything_else"
    passed = next(d for d in step.directives if d.kind == "deadline_passed")
    assert passed.data == {"deadline": "2026-03-18"}
    assert [q.action for q in step.quick_replies] == ["handoff_accept"]


def test_no_docs_case_no_data(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state("CL-2102")
    step = _turn(s, repo, sop, ex(intent="next_steps", question="how long will this take"))
    answer = step.directives[0].data
    assert answer["followup"]["kind"] == "no_specific_guidance"
    assert _kinds(step) == ["answer_question", "no_data", "anything_else"]
    assert [q.action for q in step.quick_replies] == ["handoff_accept"]
    assert ("CL-2102", "fact", "Status: open — Auto claim in progress") in _log(s)
    assert not any(k == "next_step" for _, k, _t in _log(s))


def test_no_docs_status_inquiry_has_no_no_data(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state("CL-2102")
    step = _turn(s, repo, sop, ex(intent="status_inquiry", question="what's the status?"))
    assert _kinds(step) == ["answer_question", "anything_else"]
    assert step.quick_replies == []


def test_cannot_obtain_offers_alternatives_first(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(
        s, repo, sop, ex(acts=["cannot_obtain"], question="I can't get the pathology report")
    )
    answer = step.directives[0]
    assert answer.kind == "answer_question"
    assert answer.data["followup"]["topic"] == "missing_required_material_alternatives"
    assert "default" in answer.data["alternatives"]
    assert s.alternatives_offered == ["CL-2048"]
    assert _kinds(step)[-1] == "anything_else"


def test_cannot_obtain_twice_exhausts(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, ex(acts=["cannot_obtain"]))
    step = _turn(s, repo, sop, ex(acts=["cannot_obtain"]), turn=4)
    assert _kinds(step) == ["docs_exhausted", "offer_handoff"]
    assert step.directives[0].data == {"text": docs_exhausted_text(repo)}
    assert step.directives[1].data == {"reason": "process"}
    assert [q.action for q in step.quick_replies] == ["handoff_accept"]
    assert s.alternatives_offered == ["CL-2048"]
    assert s.phase == Phase.PROCESS_CASE


def test_done_goes_post(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(acts=["done"]))
    assert s.phase == Phase.POST_PROCESS and s.sub_state == SubState.OFFER
    assert step.continue_hop is True
    assert step.directives == []


def test_deny_after_anything_else_goes_post(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, ex(intent="denial_question", question="why denied?"))
    step = _turn(s, repo, sop, ex(acts=["deny"]), turn=4)
    assert s.phase == Phase.POST_PROCESS and step.continue_hop is True


def test_end_session_action_goes_post(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, action="end_session")
    assert s.phase == Phase.POST_PROCESS


def test_switch_case_hops_to_resolve(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop, ex(acts=["select_case"], case_hints={"case_type": "auto"}))
    assert s.phase == Phase.RESOLVE_INTENT and s.sub_state == SubState.NONE
    assert step.continue_hop is True
    assert step.directives == []


def test_switch_on_different_case_hint(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, ex(case_hints={"case_id": "CL-2102"}))
    assert s.phase == Phase.RESOLVE_INTENT


def test_switch_on_different_case_type(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, ex(case_hints={"case_type": "dental"}))
    assert s.phase == Phase.RESOLVE_INTENT


def test_switch_on_select_action(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop, action="select_case:CL-2011")
    assert s.phase == Phase.RESOLVE_INTENT


def test_same_case_hint_does_not_switch(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(
        s,
        repo,
        sop,
        ex(case_hints={"case_id": "CL-2048", "case_type": "healthcare"}, question="why?"),
    )
    assert s.phase == Phase.PROCESS_CASE
    assert _kinds(step)[0] == "answer_question"


def test_switch_on_contradicting_status(repo: FixtureRepo, sop: SopConfig) -> None:
    # On the open auto claim, "my denied one" means the denied claim, not this one.
    s = _state("CL-2102")
    _turn(s, repo, sop, ex(case_hints={"status": "denied"}, question="appeal deadline?"))
    assert s.phase == Phase.RESOLVE_INTENT


def test_matching_status_or_typed_hint_does_not_switch(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state("CL-2048")  # denied
    _turn(s, repo, sop, ex(case_hints={"status": "denied"}, question="why?"))
    assert s.phase == Phase.PROCESS_CASE
    s = _state("CL-2102")  # open auto: "is my auto claim denied?" stays on it
    _turn(s, repo, sop, ex(case_hints={"case_type": "auto", "status": "denied"}, question="?"))
    assert s.phase == Phase.PROCESS_CASE
