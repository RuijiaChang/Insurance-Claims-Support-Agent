from app.llm.regex_extractor import RegexHits
from app.sop.extraction import (
    CaseHints,
    Emotion,
    Extraction,
    IdentityFields,
    RepInfo,
    reconcile,
)
from app.sop.memory import apply_extraction
from app.sop.phases import Phase
from app.sop.state import SessionState


def _margaret() -> Extraction:
    return Extraction(
        identity=IdentityFields(
            full_name="Margaret Chen",
            dob="1985-03-15",
            phone="+16505212836",
            policy_number="POL-9921",
        ),
        case_hints=CaseHints(
            case_type="healthcare", status="denied", month=1, free_text="denied in Jan"
        ),
    )


def test_reconcile_regex_overrides_format_fields() -> None:
    llm = Extraction(identity=IdentityFields(id_last4="1985", full_name="A B"))
    out = reconcile(llm, RegexHits(id_last4="4472", case_id="CL-1"))
    assert out.identity.id_last4 == "4472"
    assert out.identity.full_name == "A B"
    assert out.case_hints.case_id == "CL-1"
    assert llm.identity.id_last4 == "1985"  # input not mutated


def test_reconcile_none_uses_regex() -> None:
    hits = RegexHits(dob_raw="3/15/85", phone="+16505212836", email="a@b.co", policy_number="POL-1")
    out = reconcile(None, hits)
    assert out == Extraction.from_regex(hits)
    assert out.identity.dob == "3/15/85"
    assert out.identity.phone == "+16505212836"
    assert out.identity.email == "a@b.co"
    assert out.identity.policy_number == "POL-1"
    assert out.emotion == Emotion(label="neutral", intensity=0)
    assert out.scope == "in_scope_claim"
    assert out.caller_role == "unknown"


def test_margaret_hints_captured_in_verify() -> None:
    s = SessionState.new("s")
    apply_extraction(s, _margaret(), turn=1)
    m = s.memory
    assert (m.get("case_type"), m.get("status"), m.get("month")) == ("healthcare", "denied", "1")
    for k in ("case_type", "status", "month"):
        assert m.slots[k].captured_phase == Phase.VERIFY_ID
    assert m.get("case_quote") == "denied in Jan"
    assert s.identity.provided_count() == 3
    assert s.identity.policy_number == "POL-9921"


def test_correction_overwrites_with_history() -> None:
    s = SessionState.new("s")
    apply_extraction(s, _margaret(), turn=1)
    apply_extraction(s, Extraction(case_hints=CaseHints(month=2)), turn=2)
    assert s.memory.get("month") == "2"
    assert [(k, r.value) for k, r in s.memory.history] == [("month", "1")]
    assert s.memory.get("status") == "denied"  # None never clears


def test_identity_frozen_after_verified() -> None:
    s = SessionState.new("s")
    s.verified_party_id = "P1"
    apply_extraction(
        s,
        Extraction(
            identity=IdentityFields(dob="1990-01-01", policy_number="POL-1"),
            refused_fields=["phone"],
        ),
        turn=3,
    )
    assert s.identity.provided_count() == 0
    assert s.identity.policy_number is None
    assert s.identity.refused() == set()


def test_email_preference_remembered() -> None:
    s = SessionState.new("s")
    apply_extraction(s, Extraction(email_preference="skip"), turn=1)
    assert s.memory.get("email_preference") == "skip"


def test_refused_fields_applied() -> None:
    s = SessionState.new("s")
    apply_extraction(s, Extraction(refused_fields=["id_last4"]), turn=1)
    assert s.identity.refused() == {"id_last4"}


def test_caller_and_rep_only_in_verify() -> None:
    ex = Extraction(
        caller_role="representative",
        representative=RepInfo(rep_name="Tom", relationship="child", policyholder_name="Ann"),
    )
    s = SessionState.new("s")
    apply_extraction(s, ex, turn=1)
    assert s.caller.role == "representative"
    assert (s.caller.rep_name, s.caller.relationship, s.caller.policyholder_name) == (
        "Tom",
        "child",
        "Ann",
    )
    s2 = SessionState.new("s2")
    s2.phase = Phase.RESOLVE_INTENT
    apply_extraction(s2, ex, turn=1)
    assert s2.caller.role == "unknown"


def test_intent_and_emotion() -> None:
    s = SessionState.new("s")
    apply_extraction(
        s, Extraction(intent="denial_question", emotion=Emotion(label="angry", intensity=2)), 1
    )
    assert s.turn_intent == s.primary_intent == "denial_question"
    assert s.memory.get("intent") == "denial_question"
    assert s.last_emotion == ("angry", 2)
    apply_extraction(s, Extraction(intent="status_inquiry"), 2)
    assert s.turn_intent == "status_inquiry" and s.primary_intent == "denial_question"
    apply_extraction(s, Extraction(intent="status_inquiry", acts=["select_case"]), 3)
    assert s.primary_intent == "status_inquiry"
    apply_extraction(s, Extraction(), 4)
    assert s.turn_intent is None and s.primary_intent == "status_inquiry"


def test_to_input_normalizes() -> None:
    h = CaseHints(case_id="  ", case_type="healthcare", status="denied", year=0)
    i = h.to_input()
    assert i.case_id is None and i.year is None
    assert i.case_type == "healthcare" and not i.is_empty()
    assert CaseHints(case_id=" ", year=0).to_input().is_empty()
