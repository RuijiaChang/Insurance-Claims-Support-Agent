from typing import Any

import pytest

from app.settings import SopConfig
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, QuickReply
from app.sop.policies.emotion import emotion_directives, gate_for
from app.sop.state import Gate, SessionState
from tests.fakes import ex

BONUS = {"emotion": {"label": "angry", "intensity": 2}, "acts": ["bypass_attempt"]}
REFUSE = {"emotion": {"label": "frustrated", "intensity": 1}, "acts": ["refuse_info"]}


def _state(phase: Phase = Phase.VERIFY_ID, sub: SubState = SubState.COLLECTING) -> SessionState:
    s = SessionState.new("s1")
    s.phase = phase
    s.sub_state = sub
    return s


def _run(
    state: SessionState, sop: SopConfig, extraction: Extraction
) -> tuple[list[Directive], list[QuickReply]]:
    return emotion_directives(state, extraction, gate_for(state), sop.emotion)


def _kinds(directives: list[Directive]) -> list[str]:
    return [d.kind for d in directives]


def _data(directives: list[Directive], kind: str) -> dict[str, Any]:
    return next(d.data for d in directives if d.kind == kind)


@pytest.mark.parametrize(
    ("phase", "sub", "gate"),
    [
        (Phase.VERIFY_ID, SubState.COLLECTING, "verify"),
        (Phase.VERIFY_ID, SubState.LOCKED, "verify"),
        (Phase.VERIFY_ID, SubState.CONSENT_PENDING, "consent"),
        (Phase.VERIFY_ID, SubState.CONSENT_EXPIRED, "consent"),
        (Phase.VERIFY_ID, SubState.REP_CHECK, None),
        (Phase.VERIFY_ID, SubState.REP_DENIED, None),
        (Phase.RESOLVE_INTENT, SubState.NONE, None),
        (Phase.PROCESS_CASE, SubState.ACTIVE, None),
        (Phase.POST_PROCESS, SubState.OFFER, "email_address"),
        (Phase.POST_PROCESS, SubState.PREVIEW, "email_address"),
    ],
)
def test_gate_for(phase: Phase, sub: SubState, gate: Gate | None) -> None:
    assert gate_for(_state(phase, sub)) == gate


def test_neutral_turn_emits_nothing_and_resets_streak(sop: SopConfig) -> None:
    s = _state()
    s.counters.negative_emotion_streak = 2
    directives, replies = _run(s, sop, ex())
    assert directives == [] and replies == []
    assert s.counters.negative_emotion_streak == 0


def test_l1_first_negative_emotion_empathizes(sop: SopConfig) -> None:
    s = _state(Phase.PROCESS_CASE, SubState.ACTIVE)
    directives, replies = _run(s, sop, ex(emotion={"label": "anxious", "intensity": 1}))
    assert _kinds(directives) == ["empathize"]
    assert _data(directives, "empathize") == {"label": "anxious"}
    assert replies == []
    assert s.counters.negative_emotion_streak == 1


def test_l2_on_bonus_example(sop: SopConfig) -> None:
    """'I already told you who I am. This is ridiculous. Just tell me why my claim was denied.'"""
    s = _state()
    directives, replies = _run(s, sop, ex(**BONUS))
    assert _kinds(directives) == ["empathize", "persuade"]
    assert _data(directives, "empathize") == {"label": "angry"}
    assert _data(directives, "persuade") == {"gate": "verify"}
    assert s.counters.persuasion_attempts["verify"] == 1
    assert replies == []


def test_l2_neutral_refusal_counts_toward_budget(sop: SopConfig) -> None:
    s = _state()
    directives, _ = _run(s, sop, ex(refused_fields=["phone"]))
    # A calm refusal gets the explanation, not invented empathy ("I know it's frustrating").
    assert _kinds(directives) == ["persuade"]
    assert s.counters.persuasion_attempts["verify"] == 1


def test_no_persuasion_without_a_gate(sop: SopConfig) -> None:
    s = _state(Phase.PROCESS_CASE, SubState.ACTIVE)
    directives, _ = _run(s, sop, ex(**BONUS))
    assert _kinds(directives) == ["empathize"]
    assert s.counters.persuasion_attempts == {}


def test_l3_after_budget(sop: SopConfig) -> None:
    s = _state()
    for _ in range(sop.emotion.persuasion_budget):
        directives, _ = _run(s, sop, ex(**REFUSE))
        assert "persuade" in _kinds(directives)
    assert s.counters.persuasion_attempts["verify"] == 2

    directives, replies = _run(s, sop, ex(**REFUSE))
    assert _kinds(directives) == ["stop_persuading", "offer_handoff"]
    assert _data(directives, "offer_handoff") == {"reason": "emotion"}
    assert [q.action for q in replies] == ["handoff_accept"]
    assert s.counters.persuasion_attempts["verify"] == 2
    assert s.counters.l3_offered["verify"] is True
    assert s.handoff_offer_reason == "emotion"


def test_l3_on_negative_streak(sop: SopConfig) -> None:
    s = _state(Phase.PROCESS_CASE, SubState.ACTIVE)
    angry = ex(emotion={"label": "frustrated", "intensity": 2})
    _run(s, sop, angry)
    _run(s, sop, angry)
    directives, replies = _run(s, sop, angry)
    assert s.counters.negative_emotion_streak == 3
    assert _kinds(directives) == ["stop_persuading", "offer_handoff"]
    assert [q.action for q in replies] == ["handoff_accept"]


def test_l3_on_abuse(sop: SopConfig) -> None:
    s = _state()
    directives, _ = _run(s, sop, ex(emotion={"label": "angry", "intensity": 3}))
    assert _kinds(directives) == ["stop_persuading", "offer_handoff"]
    assert "verify" not in s.counters.persuasion_attempts


def test_l3_declined_only_restates(sop: SopConfig) -> None:
    s = _state()
    for _ in range(sop.emotion.persuasion_budget + 1):
        _run(s, sop, ex(**REFUSE))
    assert s.counters.l3_offered["verify"] is True

    directives, replies = _run(s, sop, ex(acts=["deny"]))
    assert s.counters.l3_declined["verify"] is True
    assert _kinds(directives) == ["restate_requirement"]
    assert _data(directives, "restate_requirement") == {"gate": "verify"}
    assert [q.action for q in replies] == ["handoff_accept"]

    # Still angry and refusing: no more empathy, persuasion or offers.
    directives, replies = _run(s, sop, ex(**BONUS))
    assert _kinds(directives) == ["restate_requirement"]
    assert [q.action for q in replies] == ["handoff_accept"]
    assert s.counters.persuasion_attempts["verify"] == 2
