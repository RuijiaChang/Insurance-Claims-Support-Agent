import itertools

import pytest

from app.sop.phases import ALLOWED, IllegalTransition, Phase, SubState, transition
from app.sop.plan import Directive, PolicyCtx, StepResult, TurnPlan
from app.sop.state import IdentityClaims, Memory, SessionState

P = Phase
SPEC: dict[Phase, set[Phase]] = {
    P.VERIFY_ID: {P.RESOLVE_INTENT, P.HANDOFF, P.CLOSED},
    P.RESOLVE_INTENT: {P.PROCESS_CASE, P.POST_PROCESS, P.HANDOFF, P.CLOSED},
    P.PROCESS_CASE: {P.RESOLVE_INTENT, P.POST_PROCESS, P.HANDOFF},
    P.POST_PROCESS: {P.PROCESS_CASE, P.CLOSED, P.HANDOFF},
    P.HANDOFF: set(),
    P.CLOSED: set(),
}


@pytest.mark.parametrize("a,b", list(itertools.product(Phase, Phase)))
def test_allowed_table_matches_spec(a: Phase, b: Phase) -> None:
    assert (b in ALLOWED[a]) == (b in SPEC[a])


def test_illegal_transition_raises() -> None:
    s = SessionState.new("s1")
    with pytest.raises(IllegalTransition, match="VERIFY_ID->PROCESS_CASE"):
        transition(s, Phase.PROCESS_CASE, SubState.ACTIVE)
    assert s.phase == Phase.VERIFY_ID


def test_same_phase_only_sets_sub_state() -> None:
    s = SessionState.new("s1")
    transition(s, Phase.VERIFY_ID, SubState.LOCKED)
    assert (s.phase, s.sub_state) == (Phase.VERIFY_ID, SubState.LOCKED)


def test_legal_transition_sets_both() -> None:
    s = SessionState.new("s1")
    transition(s, Phase.RESOLVE_INTENT, SubState.NONE)
    assert s.phase == Phase.RESOLVE_INTENT


def test_terminal_has_no_exit() -> None:
    assert ALLOWED[Phase.HANDOFF] == frozenset()
    assert ALLOWED[Phase.CLOSED] == frozenset()
    s = SessionState.new("s1")
    transition(s, Phase.CLOSED, SubState.NONE)
    with pytest.raises(IllegalTransition):
        transition(s, Phase.RESOLVE_INTENT, SubState.NONE)


def test_new_session_defaults() -> None:
    s = SessionState.new("s1", "slow")
    assert s.phase == Phase.VERIFY_ID and s.sub_state == SubState.COLLECTING
    assert s.access_granted is False and s.consent.scenario == "slow"
    assert s.identity.provided_count() == 0
    assert set(s.identity.fields) == {"full_name", "dob", "phone", "email", "id_last4"}
    assert SessionState.new("a").transcript is not SessionState.new("b").transcript


def test_identity_add_dedup_and_counts() -> None:
    c = IdentityClaims()
    c.add("dob", "1985-03-15", 1)
    c.add("dob", " 1985-03-15 ", 2)
    c.add("dob", "  ", 3)
    assert c.values()["dob"] == ["1985-03-15"]
    assert c.provided_count() == 1
    assert c.fields["dob"].captured_turn == 2


def test_refused_then_provided() -> None:
    c = IdentityClaims()
    c.refuse("phone", 1)
    assert c.refused() == {"phone"}
    assert c.provided_count() == 0
    c.add("phone", "6505212836", 2)
    assert c.fields["phone"].status == "provided"
    assert c.refused() == set()


def test_remaining_options_order() -> None:
    c = IdentityClaims()
    assert c.remaining_options() == ["full_name", "dob", "phone", "email", "id_last4"]
    c.add("dob", "x", 1)
    c.refuse("email", 1)
    assert c.remaining_options() == ["full_name", "phone", "id_last4"]


def test_memory_overwrite_keeps_history() -> None:
    m = Memory()
    m.set("case_id", "CL-1", 1, Phase.RESOLVE_INTENT)
    m.set("case_id", "CL-1", 2, Phase.PROCESS_CASE)
    assert m.history == [] and m.slots["case_id"].captured_turn == 1
    m.set("case_id", "CL-2", 3, Phase.PROCESS_CASE)
    assert m.get("case_id") == "CL-2"
    assert [(k, r.value) for k, r in m.history] == [("case_id", "CL-1")]
    m.mark_used("case_id", Phase.POST_PROCESS)
    assert m.slots["case_id"].used_phase == Phase.POST_PROCESS
    assert m.get("year") is None
    with pytest.raises(ValueError):
        m.set("bogus", "x", 1, Phase.VERIFY_ID)


def test_state_json_round_trip() -> None:
    s = SessionState.new("s1")
    s.last_emotion = ("angry", 2)
    s.identity.add("dob", "1985-03-15", 1)
    s.memory.set("year", "2025", 1, Phase.VERIFY_ID)
    s.counters.persuasion_attempts["verify"] = 1
    r = SessionState.model_validate_json(s.model_dump_json())
    assert r == s and r.last_emotion == ("angry", 2)


def test_plan_types() -> None:
    d = Directive(kind="closing")
    assert d.data == {}
    r = StepResult(directives=[d], quick_replies=[])
    assert r.fact_scope == "none" and r.transition is None and not r.continue_hop
    t = TurnPlan(directives=[d], quick_replies=[], fact_scope="none", hops=[Phase.VERIFY_ID])
    assert t.hops == [Phase.VERIFY_ID]
    assert "user_text" in PolicyCtx.__dataclass_fields__
