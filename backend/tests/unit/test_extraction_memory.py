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
    out = reconcile(llm, RegexHits(id_last4="4472", case_id="CL-1"), "A B, last four 4472, CL-1")
    assert out.identity.id_last4 == "4472"
    assert out.identity.full_name == "A B"
    assert out.case_hints.case_id == "CL-1"
    assert llm.identity.id_last4 == "1985"  # input not mutated


def test_reconcile_drops_identity_values_the_caller_did_not_say() -> None:
    text = "I'm Margaret Chen, calling about my denied claim"
    llm = Extraction(
        identity=IdentityFields(
            full_name="Margaret Chen",
            dob="1985-03-15",
            id_last4="4472",
            phone="+16505212836",
            email="margaret@email.com",
            policy_number="POL-9921",
        )
    )
    out = reconcile(llm, RegexHits(), text)
    assert out.identity == IdentityFields(full_name="Margaret Chen")
    state = SessionState.new("s1")
    apply_extraction(state, out, 1)
    assert state.identity.provided_count() == 1


def test_reconcile_keeps_grounded_identity_values() -> None:
    text = (
        "Margaret Chen here, born March 15, 1985, cell (650) 521-2836, "
        "Margaret@Email.com, policy pol-9921, ssn ends 4472"
    )
    llm = Extraction(
        identity=IdentityFields(
            full_name="margaret chen",
            dob="1985-03-15",  # the model normalized the natural-language date
            phone="+16505212836",
            email="margaret@email.com",
            id_last4="4472",
            policy_number="POL-9921",
        )
    )
    out = reconcile(llm, RegexHits(), text)
    assert out.identity == llm.identity


def test_reconcile_drops_partial_or_altered_values() -> None:
    text = "My name is Margaret, born 1985-03-16, last four 44721"
    llm = Extraction(
        identity=IdentityFields(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472")
    )
    out = reconcile(llm, RegexHits(), text)
    assert out.identity == IdentityFields()


def test_reconcile_none_uses_regex() -> None:
    hits = RegexHits(dob_raw="3/15/85", phone="+16505212836", email="a@b.co", policy_number="POL-1")
    out = reconcile(None, hits, "")
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


def _copied_from_agent() -> Extraction:
    # What gpt-4.1-mini returned live for "That's all, thanks" after the agent described
    # the auto claim: every hint was lifted from the agent's own reply.
    return Extraction(
        case_hints=CaseHints(
            case_type="auto",
            status="open",
            month=2,
            year=2026,
            free_text="Your open auto claim from February 28, 2026",
        ),
        acts=["done"],
    )


def test_reconcile_drops_case_hints_the_caller_did_not_say() -> None:
    out = reconcile(_copied_from_agent(), RegexHits(), "That's all, thanks")
    assert out.case_hints == CaseHints()


def test_reconcile_keeps_case_hints_grounded_in_caller_words() -> None:
    llm = Extraction(case_hints=CaseHints(case_type="auto", free_text="my car claim"))
    out = reconcile(llm, RegexHits(), "And what about my car claim?")
    assert out.case_hints.case_type == "auto" and out.case_hints.free_text == "my car claim"
    llm = Extraction(case_hints=CaseHints(case_type="dental", month=11, free_text="dental thing"))
    out = reconcile(llm, RegexHits(), "the dentist one from November")
    assert out.case_hints.case_type == "dental" and out.case_hints.month == 11
    assert out.case_hints.free_text is None  # not a quote of what they said


def test_reconcile_keeps_case_hints_when_caller_selects_a_listed_option() -> None:
    llm = _copied_from_agent().model_copy(update={"acts": ["select_case"]})
    out = reconcile(llm, RegexHits(), "the second one")
    assert out.case_hints.case_type == "auto"


def test_reconcile_drops_hint_fields_carried_over_from_context() -> None:
    # Live: on the auto claim, "my denied one" came back as case_type=auto + status=denied.
    llm = Extraction(
        case_hints=CaseHints(case_type="auto", status="denied", free_text="my denied one")
    )
    out = reconcile(llm, RegexHits(), "Is there an appeal deadline on my denied one?")
    assert out.case_hints == CaseHints(status="denied", free_text="my denied one")
