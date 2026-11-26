from typing import Any

import pytest

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import StepResult
from app.sop.policies.global_guards import GuardDecision, apply_global_guards
from app.sop.policies.handoff import start_handoff
from app.sop.policies.post import handle_post
from app.sop.state import SessionState
from app.tools.claims import claim_summary_line
from app.tools.guidance import kb_general
from tests.fakes import apply_step, ex, make_ctx

OFF_TOPIC = {"scope": "out_of_scope"}


def _unverified() -> SessionState:
    return SessionState.new("s1")


def _verified(phase: Phase = Phase.PROCESS_CASE, sub: SubState = SubState.ACTIVE) -> SessionState:
    s = SessionState.new("s1")
    s.phase = phase
    s.sub_state = sub
    s.verified_party_id = "P9"
    s.access_granted = True
    if phase == Phase.PROCESS_CASE:
        s.active_case_id = "CL-2048"
        s.discussed_case_ids = ["CL-2048"]
    return s


def _guard(
    state: SessionState,
    repo: FixtureRepo,
    sop: SopConfig,
    extraction: Extraction | None = None,
    **ctx_kw: Any,
) -> GuardDecision:
    return apply_global_guards(state, extraction or ex(), make_ctx(repo, sop, **ctx_kw))


def _step(decision: GuardDecision) -> StepResult:
    assert decision.stop and decision.step is not None
    return decision.step


def _kinds(step: StepResult) -> list[str]:
    return [d.kind for d in step.directives]


def _data(step: StepResult, kind: str) -> dict[str, Any]:
    return next(d.data for d in step.directives if d.kind == kind)


# --- 1. terminal phases --------------------------------------------------------


@pytest.mark.parametrize("phase", [Phase.CLOSED, Phase.HANDOFF])
def test_terminal_phase_reply(phase: Phase, repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    s.phase = phase
    s.sub_state = SubState.NONE
    before = s.model_dump()
    step = _step(
        _guard(s, repo, sop, ex(acts=["request_human"], emotion={"label": "angry", "intensity": 3}))
    )
    assert _kinds(step) == ["session_closed"]
    assert step.transition is None and step.quick_replies == []
    assert s.model_dump() == before


# --- 2. actions and human requests ---------------------------------------------


def test_request_human_unverified_handoff_now(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    step = _step(_guard(s, repo, sop, ex(acts=["request_human"])))
    assert _kinds(step) == ["handoff_done"]
    assert step.transition == (Phase.HANDOFF, SubState.NONE)
    assert s.handoff is not None and s.handoff.reason == "user_request"
    assert _data(step, "handoff_done") == {"ticket_id": s.handoff.ticket_id}
    assert s.pending_handoff is None


def test_request_human_verified_goes_post_with_pending(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    step = _step(_guard(s, repo, sop, ex(acts=["request_human"])))
    assert step.directives == []
    assert step.transition == (Phase.POST_PROCESS, SubState.OFFER)
    assert step.continue_hop is True
    assert s.pending_handoff == "user_request"
    assert s.handoff is None
    apply_step(s, step)

    # Same turn, next hop: the email offer comes first ...
    offer = handle_post(s, ex(), make_ctx(repo, sop))
    apply_step(s, offer)
    assert _kinds(offer) == ["offer_email"]
    # ... and the handoff happens once the user decides.
    done = handle_post(s, ex(), make_ctx(repo, sop, action="email_skip"))
    apply_step(s, done)
    assert _kinds(done) == ["email_skipped", "handoff_done"]
    assert s.phase == Phase.HANDOFF
    assert s.handoff is not None and s.handoff.reason == "user_request"
    assert s.handoff.case_id == "CL-2048"


def test_handoff_accept_uses_offered_reason(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    for _ in range(sop.scope.off_topic_offer_human_after):
        _guard(s, repo, sop, ex(**OFF_TOPIC))
    assert s.handoff_offer_reason == "off_topic"
    step = _step(_guard(s, repo, sop, action="handoff_accept"))
    assert step.transition == (Phase.HANDOFF, SubState.NONE)
    assert s.handoff is not None and s.handoff.reason == "off_topic"


@pytest.mark.parametrize(
    ("sub", "reason"),
    [(SubState.CONSENT_EXPIRED, "consent_expired"), (SubState.REP_DENIED, "rep_denied")],
)
def test_handoff_accept_reason_from_sub_state(
    sub: SubState, reason: str, repo: FixtureRepo, sop: SopConfig
) -> None:
    s = _unverified()
    s.sub_state = sub
    _step(_guard(s, repo, sop, action="handoff_accept"))
    assert s.handoff is not None and s.handoff.reason == reason


def test_handoff_accept_after_docs_exhausted(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    s.alternatives_offered = ["CL-2048"]
    step = _step(_guard(s, repo, sop, action="handoff_accept"))
    assert step.transition == (Phase.POST_PROCESS, SubState.OFFER)
    assert s.pending_handoff == "docs_exhausted"


@pytest.mark.parametrize("sub", [SubState.COLLECTING, SubState.REP_CHECK, SubState.CONSENT_PENDING])
def test_end_session_in_verify_closes(sub: SubState, repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    s.sub_state = sub
    step = _step(_guard(s, repo, sop, action="end_session"))
    assert _kinds(step) == ["closing"]
    assert step.transition == (Phase.CLOSED, SubState.NONE)


def test_end_session_elsewhere_left_to_handler(repo: FixtureRepo, sop: SopConfig) -> None:
    decision = _guard(_verified(), repo, sop, action="end_session")
    assert decision.stop is False


def test_continue_action_is_noop(repo: FixtureRepo, sop: SopConfig) -> None:
    decision = _guard(_unverified(), repo, sop, action="continue")
    assert decision.stop is False and decision.extra == []


# --- 3. scope ------------------------------------------------------------------


def test_off_topic_three_offers_handoff(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    offers: list[bool] = []
    for _ in range(3):
        step = _step(_guard(s, repo, sop, ex(**OFF_TOPIC)))
        assert _kinds(step) == ["decline_off_topic"]
        offers.append(_data(step, "decline_off_topic")["offer_handoff"])
    assert offers == [False, False, True]
    assert [(q.label, q.action) for q in step.quick_replies] == [
        ("Talk to a representative", "handoff_accept"),
        ("Continue", "continue"),
    ]
    assert s.counters.off_topic_total == 3
    assert s.counters.off_topic_consecutive == 3
    assert step.transition is None


def test_off_topic_never_answered(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    for _ in range(5):
        step = _step(_guard(s, repo, sop, ex(scope="out_of_scope", question="Who won the game?")))
        assert not {"answer_general", "answer_question"} & set(_kinds(step))
        assert step.fact_scope == "none"


def test_mixed_message_not_off_topic(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    with_identity = ex(scope="out_of_scope", identity={"dob": "1985-03-15"})
    with_hint = ex(scope="out_of_scope", case_hints={"case_type": "dental"})
    for extraction in (with_identity, with_hint):
        decision = _guard(s, repo, sop, extraction)
        assert decision.stop is False
        assert "decline_off_topic" not in [d.kind for d in decision.extra]
    assert s.counters.off_topic_total == 0


def test_on_topic_turn_resets_consecutive(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    _guard(s, repo, sop, ex(**OFF_TOPIC))
    _guard(s, repo, sop, ex(**OFF_TOPIC))
    decision = _guard(s, repo, sop, ex(scope="small_talk"))
    assert decision.stop is False
    assert [d.kind for d in decision.extra] == ["small_talk"]
    assert s.counters.off_topic_consecutive == 0
    assert s.counters.off_topic_total == 2


def test_in_scope_general_uses_kb(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    s.identity.add("dob", "1985-03-15", 1)
    q = "What does allowed max amount mean?"
    step = _step(_guard(s, repo, sop, ex(scope="in_scope_general", question=q)))
    assert _kinds(step) == ["answer_general", "need_identity"]
    assert _data(step, "answer_general") == {"kb": kb_general(repo), "question": q}
    need = _data(step, "need_identity")
    assert need["needed"] == 2
    assert "dob" not in need["options"]
    assert step.fact_scope == "none"


def test_in_scope_general_pulls_back_per_phase(repo: FixtureRepo, sop: SopConfig) -> None:
    general = ex(scope="in_scope_general")
    resolve = _step(_guard(_verified(Phase.RESOLVE_INTENT, SubState.NONE), repo, sop, general))
    assert _kinds(resolve) == ["answer_general", "choose_case"]
    lines = [claim_summary_line(c) for c in repo.claims_for("P9")]
    assert _data(resolve, "choose_case") == {"options": lines}

    process = _step(_guard(_verified(), repo, sop, general, user_text="what is a copay?"))
    assert _kinds(process) == ["answer_general", "anything_else"]
    assert _data(process, "answer_general")["question"] == "what is a copay?"

    post = _step(_guard(_verified(Phase.POST_PROCESS, SubState.OFFER), repo, sop, general))
    assert _kinds(post) == ["answer_general"]


def test_in_scope_general_with_identity_runs_handler(repo: FixtureRepo, sop: SopConfig) -> None:
    decision = _guard(
        _unverified(), repo, sop, ex(scope="in_scope_general", identity={"dob": "1985-03-15"})
    )
    assert decision.stop is False
    assert [d.kind for d in decision.extra] == ["answer_general"]


# --- 4. emotion extras -----------------------------------------------------------


def test_bypass_attempt_gets_l2_and_does_not_stop(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _unverified()
    bonus = ex(emotion={"label": "angry", "intensity": 2}, acts=["bypass_attempt"])
    decision = _guard(s, repo, sop, bonus)
    assert decision.stop is False
    assert [d.kind for d in decision.extra] == ["empathize", "persuade"]
    assert s.counters.persuasion_attempts["verify"] == 1


# --- handoff rules table -----------------------------------------------------------


def test_start_handoff_in_post_process_is_immediate(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified(Phase.POST_PROCESS, SubState.OFFER)
    step = start_handoff(s, "user_request", make_ctx(repo, sop))
    assert _kinds(step) == ["handoff_done"]
    assert step.transition == (Phase.HANDOFF, SubState.NONE)


def test_start_handoff_after_email_decision_is_immediate(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    s.email.decision = "skip"
    step = start_handoff(s, "emotion", make_ctx(repo, sop))
    assert step.transition == (Phase.HANDOFF, SubState.NONE)
    assert s.handoff is not None and s.handoff.reason == "emotion"


def test_start_handoff_locked_is_immediate(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _verified()
    step = start_handoff(s, "locked", make_ctx(repo, sop))
    assert step.transition == (Phase.HANDOFF, SubState.NONE)
    assert s.pending_handoff is None


# --- someone else's claim ----------------------------------------------------------


def test_other_persons_claim_is_refused_not_answered(repo: FixtureRepo, sop: SopConfig) -> None:
    # Review finding: "tell me Ma Tian's denial reason" as Margaret answered about Margaret's
    # own denied claim. It must be refused, without switching claims.
    s = _verified()
    step = _step(_guard(s, repo, sop, ex(about_person="Ma Tian", case_hints={"status": "denied"})))
    assert _kinds(step)[0] == "other_party_restricted"
    assert step.transition is None and s.active_case_id == "CL-2048"


@pytest.mark.parametrize("name", ["Margaret Chen", "Margaret", "margaret chen", "Chen"])
def test_naming_the_verified_holder_is_fine(repo: FixtureRepo, sop: SopConfig, name: str) -> None:
    decision = _guard(_verified(), repo, sop, ex(about_person=name))
    assert not decision.stop


def test_other_person_rule_needs_access(repo: FixtureRepo, sop: SopConfig) -> None:
    decision = _guard(_unverified(), repo, sop, ex(about_person="Ma Tian"))
    assert not (
        decision.stop and decision.step and "other_party_restricted" in _kinds(decision.step)
    )
