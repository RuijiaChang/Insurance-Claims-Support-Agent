import json
from typing import Any

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.extraction import Extraction
from app.sop.memory import apply_extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import StepResult
from app.sop.policies.verify import handle_verify
from app.sop.state import SessionState
from tests.fakes import apply_step, ex, make_ctx

MARGARET: dict[str, str] = {
    "full_name": "Margaret Chen",
    "dob": "1985-03-15",
    "phone": "(650) 521-2836",
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
    extraction: Extraction | None = None,
    turn: int = 1,
    **ctx_kw: Any,
) -> StepResult:
    """Mirror the pipeline: fold the extraction into memory, run the policy, apply transition."""
    extraction = extraction or ex()
    apply_extraction(state, extraction, turn)
    step = handle_verify(state, extraction, make_ctx(repo, sop, turn=turn, **ctx_kw))
    apply_step(state, step)
    return step


def _kinds(step: StepResult) -> list[str]:
    return [d.kind for d in step.directives]


def _directive(step: StepResult, kind: str) -> dict[str, Any]:
    return next(d.data for d in step.directives if d.kind == kind)


def _actions(step: StepResult) -> set[str]:
    return {q.action for q in step.quick_replies}


def _rep_to_consent_pending(
    repo: FixtureRepo, sop: SopConfig, scenario: str = "default"
) -> SessionState:
    state = SessionState.new("s1", consent_scenario=scenario)
    step = _turn(state, repo, sop, ex(identity=MARGARET, **REP))
    assert state.sub_state == SubState.CONSENT_PENDING, _kinds(step)
    return state


def _poll(state: SessionState, repo: FixtureRepo, sop: SopConfig, turn: int) -> StepResult:
    return _turn(state, repo, sop, turn=turn, event="consent_poll")


def test_two_fields_need_one_more(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(state, repo, sop, ex(identity={"full_name": "Margaret Chen", "dob": "1985-03-15"}))
    assert _kinds(step) == ["need_identity"]
    data = _directive(step, "need_identity")
    assert data["needed"] == 1
    assert data["options"] == ["phone", "email", "id_last4"]
    assert step.transition is None
    assert state.phase == Phase.VERIFY_ID and state.sub_state == SubState.COLLECTING
    assert state.verification_failures == 0


def test_pass_policyholder_hops(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(state, repo, sop, ex(identity=MARGARET))
    assert _kinds(step) == ["confirm_verified"]
    assert step.continue_hop is True
    assert state.phase == Phase.RESOLVE_INTENT and state.sub_state == SubState.NONE
    assert state.access_granted is True
    assert state.verified_party_id == "P9"
    assert state.identity.matched_fields == ["dob", "full_name", "phone"]


def test_fail_does_not_name_fields(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    wrong = {"full_name": "Margaret Chen", "dob": "1985-03-16", "phone": "(650) 521-2836"}
    step = _turn(state, repo, sop, ex(identity=wrong))
    assert _kinds(step) == ["verify_failed"]
    assert state.verification_failures == 1
    assert state.access_granted is False and state.verified_party_id is None
    assert state.phase == Phase.VERIFY_ID and state.sub_state == SubState.COLLECTING
    assert state.pending_question is not None and state.pending_question.kind == "need_identity"
    payload = json.dumps([d.model_dump() for d in step.directives])
    for leak in ("dob", "phone", "full_name", "matched", "mismatch", "P9", "Margaret"):
        assert leak not in payload
    assert _directive(step, "verify_failed")["options"] == ["email", "id_last4"]
    assert state.identity.matched_fields == []


def test_corrected_value_in_same_message_passes(repo: FixtureRepo, sop: SopConfig) -> None:
    # "DOB 1985-03-16, sorry, 1985-03-15" leaves both values on the dob field in one turn.
    state = SessionState.new("s1")
    state.identity.add("dob", "1985-03-16", 1)
    extraction = ex(
        identity={"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}
    )
    step = _turn(state, repo, sop, extraction)
    assert state.identity.fields["dob"].values == ["1985-03-16", "1985-03-15"]
    assert state.identity.provided_count() == 3
    assert _kinds(step) == ["confirm_verified"]
    assert state.access_granted is True


def test_rep_registered_goes_consent_pending_without_access(
    repo: FixtureRepo, sop: SopConfig
) -> None:
    state = SessionState.new("s1")
    step = _turn(state, repo, sop, ex(identity=MARGARET, **REP))
    assert _kinds(step) == ["consent_sent"]
    assert step.quick_replies == []
    assert step.continue_hop is False
    assert state.phase == Phase.VERIFY_ID and state.sub_state == SubState.CONSENT_PENDING
    assert state.access_granted is False
    assert state.verified_party_id == "P9"
    assert state.consent.status == "pending"
    masked = _directive(step, "consent_sent")["masked_phone"]
    assert masked.endswith("36")
    assert "650" not in masked


def test_rep_unregistered_denied(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    stranger = {
        "caller_role": "representative",
        "representative": {"rep_name": "Kevin Park", "relationship": "spouse"},
    }
    step = _turn(state, repo, sop, ex(identity=MARGARET, **stranger))
    assert _kinds(step) == ["rep_denied"]
    assert _actions(step) == {"handoff_accept", "end_session"}
    assert state.sub_state == SubState.REP_DENIED
    assert state.access_granted is False

    again = _turn(state, repo, sop, ex(), turn=2)
    assert _kinds(again) == ["rep_denied"]
    assert state.sub_state == SubState.REP_DENIED

    end = _turn(state, repo, sop, ex(), turn=3, action="end_session")
    assert _kinds(end) == ["closing"]
    assert state.phase == Phase.CLOSED


def test_rep_missing_details_asks_then_checks(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(state, repo, sop, ex(identity=MARGARET, caller_role="representative"))
    assert _kinds(step) == ["rep_ask_details"]
    assert state.sub_state == SubState.REP_CHECK
    assert state.access_granted is False

    step = _turn(state, repo, sop, ex(representative=REP["representative"]), turn=2)
    assert _kinds(step) == ["consent_sent"]
    assert state.sub_state == SubState.CONSENT_PENDING


def test_consent_default_approves_on_second_poll(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _rep_to_consent_pending(repo, sop)
    first = _poll(state, repo, sop, turn=2)
    assert _kinds(first) == ["consent_waiting"]
    assert state.access_granted is False
    second = _poll(state, repo, sop, turn=3)
    assert _kinds(second) == ["consent_approved"]
    assert second.continue_hop is False
    assert state.phase == Phase.RESOLVE_INTENT
    assert state.access_granted is True


def test_user_message_also_polls_consent(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _rep_to_consent_pending(repo, sop)
    _turn(state, repo, sop, ex(), turn=2)
    _turn(state, repo, sop, ex(), turn=3)
    assert state.access_granted is True


def test_consent_timeout_expired_options(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _rep_to_consent_pending(repo, sop, scenario="timeout")
    for turn in range(2, 6):
        assert _kinds(_poll(state, repo, sop, turn)) == ["consent_waiting"]
    step = _poll(state, repo, sop, 6)
    assert _kinds(step) == ["consent_expired"]
    assert _directive(step, "consent_expired")["can_resend"] is True
    assert state.sub_state == SubState.CONSENT_EXPIRED
    assert _actions(step) == {"consent_resend", "handoff_accept", "end_session"}
    assert state.access_granted is False


def test_resend_once_only(repo: FixtureRepo, sop: SopConfig) -> None:
    state = _rep_to_consent_pending(repo, sop, scenario="timeout")
    for turn in range(2, 7):
        _poll(state, repo, sop, turn)
    assert state.sub_state == SubState.CONSENT_EXPIRED

    resent = _turn(state, repo, sop, ex(), turn=7, action="consent_resend")
    assert _kinds(resent) == ["consent_sent"]
    assert state.sub_state == SubState.CONSENT_PENDING
    assert state.consent.status == "pending" and state.consent.resends == 1

    for turn in range(8, 13):
        step = _poll(state, repo, sop, turn)
    assert _kinds(step) == ["consent_expired"]
    assert _directive(step, "consent_expired")["can_resend"] is False
    assert _actions(step) == {"handoff_accept", "end_session"}

    refused = _turn(state, repo, sop, ex(), turn=13, action="consent_resend")
    assert _kinds(refused) == ["consent_expired"]
    assert "consent_resend" not in _actions(refused)
    assert state.sub_state == SubState.CONSENT_EXPIRED
    assert state.consent.resends == 1

    end = _turn(state, repo, sop, ex(), turn=14, action="end_session")
    assert _kinds(end) == ["closing"]
    assert state.phase == Phase.CLOSED


def test_refuse_offers_alternatives(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(
        state,
        repo,
        sop,
        ex(
            identity={"full_name": "Margaret Chen"},
            refused_fields=["id_last4"],
            acts=["refuse_info"],
        ),
    )
    assert _kinds(step) == ["need_identity", "offer_alternatives"]
    assert _directive(step, "need_identity")["needed"] == 2
    assert _directive(step, "offer_alternatives")["options"] == ["dob", "phone", "email"]
    assert step.quick_replies == []

    # Refusing two more leaves name + one option: fewer than 3 reachable -> offer a human.
    step = _turn(
        state, repo, sop, ex(refused_fields=["phone", "email"], acts=["refuse_info"]), turn=2
    )
    assert _kinds(step) == ["need_identity", "offer_alternatives", "offer_handoff"]
    assert _directive(step, "offer_handoff") == {"reason": "verify"}
    assert _actions(step) == {"handoff_accept"}
    assert state.pending_question is not None and state.pending_question.kind == "offer_handoff"
    assert state.verification_failures == 0


def test_ask_why_explains(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(state, repo, sop, ex(acts=["ask_why"]))
    assert "explain_why" in _kinds(step)
    assert _directive(step, "explain_why") == {"gate": "verify"}
    assert "need_identity" in _kinds(step)
    assert _directive(step, "need_identity")["needed"] == 3


def test_hint_acknowledged(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(
        state,
        repo,
        sop,
        ex(
            case_hints={"case_type": "healthcare", "status": "denied", "free_text": "denied in Jan"}
        ),
    )
    assert _kinds(step)[0] == "acknowledge_hint"
    assert _directive(step, "acknowledge_hint") == {"quote": "denied in Jan"}

    later = _turn(state, repo, sop, ex(identity={"full_name": "Margaret Chen"}), turn=2)
    assert "acknowledge_hint" not in _kinds(later)

    state2 = SessionState.new("s2")
    step2 = _turn(state2, repo, sop, ex(case_hints={"case_type": "dental", "status": "denied"}))
    assert _directive(step2, "acknowledge_hint")["quote"] == "your denied dental claim"


def test_no_new_input_repeats_failure_without_counting(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    _turn(state, repo, sop, ex(identity={**MARGARET, "dob": "1985-03-16"}))
    assert state.verification_failures == 1
    step = _turn(state, repo, sop, ex(), turn=2)
    assert _kinds(step) == ["verify_failed"]
    assert _directive(step, "verify_failed")["repeat"] is True
    assert state.verification_failures == 1


def test_three_failures_lock_and_handoff(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    attempts = ["1985-03-16", "1985-03-17", "1985-03-18"]
    for turn, dob in enumerate(attempts, start=1):
        step = _turn(state, repo, sop, ex(identity={**MARGARET, "dob": dob}), turn=turn)
    assert state.verification_failures == 3
    assert _kinds(step) == ["locked", "handoff_done"]
    assert state.phase == Phase.HANDOFF
    assert state.handoff is not None
    assert state.handoff.reason == "locked"
    assert state.handoff.case_id is None
    assert state.handoff.verified is False
    assert _directive(step, "handoff_done")["ticket_id"] == state.handoff.ticket_id
    assert state.access_granted is False


def _one_failure(state: SessionState, repo: FixtureRepo, sop: SopConfig) -> None:
    _turn(state, repo, sop, ex(identity={**MARGARET, "dob": "1985-03-16"}))
    assert state.verification_failures == 1


def test_refusing_unprovided_field_after_failure_does_not_recount(
    repo: FixtureRepo, sop: SopConfig
) -> None:
    state = SessionState.new("s1")
    _one_failure(state, repo, sop)
    step = _turn(state, repo, sop, ex(refused_fields=["email"], acts=["refuse_info"]), turn=2)
    assert state.verification_failures == 1
    assert _directive(step, "verify_failed")["repeat"] is True
    step = _turn(state, repo, sop, ex(refused_fields=["id_last4"], acts=["refuse_info"]), turn=3)
    assert state.verification_failures == 1
    assert state.phase == Phase.VERIFY_ID


def test_restating_same_value_after_failure_does_not_recount(
    repo: FixtureRepo, sop: SopConfig
) -> None:
    state = SessionState.new("s1")
    _one_failure(state, repo, sop)
    for turn in (2, 3, 4):
        step = _turn(state, repo, sop, ex(identity={"full_name": "Margaret Chen"}), turn=turn)
        assert _directive(step, "verify_failed")["repeat"] is True
    assert state.verification_failures == 1
    assert state.phase == Phase.VERIFY_ID


def test_changed_value_after_failure_compares_again(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    _one_failure(state, repo, sop)
    step = _turn(state, repo, sop, ex(identity={"dob": "1985-03-17"}), turn=2)
    assert state.verification_failures == 2
    assert "repeat" not in _directive(step, "verify_failed")

    other = SessionState.new("s2")
    _one_failure(other, repo, sop)
    step = _turn(other, repo, sop, ex(identity={"dob": "1985-03-15"}), turn=2)
    assert _kinds(step) == ["confirm_verified"]
    assert other.verification_failures == 1


def test_no_hint_acknowledgement_when_verified_the_same_turn(
    repo: FixtureRepo, sop: SopConfig
) -> None:
    # The claim is pulled up in this same turn, which already shows it was remembered.
    state = SessionState.new("s1")
    step = _turn(
        state,
        repo,
        sop,
        ex(identity=MARGARET, case_hints={"case_type": "healthcare", "free_text": "my claim"}),
    )
    assert state.access_granted
    assert _kinds(step) == ["confirm_verified"]


def test_representative_still_gets_hint_acknowledgement(repo: FixtureRepo, sop: SopConfig) -> None:
    state = SessionState.new("s1")
    step = _turn(
        state,
        repo,
        sop,
        ex(
            identity=MARGARET,
            case_hints={"case_type": "healthcare", "free_text": "her claim"},
            **REP,
        ),
    )
    assert not state.access_granted
    assert "acknowledge_hint" in _kinds(step)
