from typing import Any, get_args

import pytest

from app.sop.context import ResponderContext
from app.sop.phases import Phase
from app.sop.plan import Directive, DirectiveKind
from app.sop.templates import render

MINIMAL_DATA: dict[str, dict[str, Any]] = {
    "need_identity": {"needed": 2, "options": ["dob", "phone"]},
    "verify_failed": {"options": ["email"]},
    "acknowledge_hint": {"quote": "my denied claim"},
    "explain_why": {"gate": "verify"},
    "offer_alternatives": {"options": ["email"]},
    "empathize": {"label": "angry"},
    "persuade": {"gate": "verify"},
    "restate_requirement": {"gate": "verify"},
    "offer_handoff": {"reason": "verify"},
    "handoff_done": {"ticket_id": "HT-1"},
    "rep_ask_details": {"missing": ["rep_name"]},
    "consent_sent": {"masked_phone": "***-***-**36"},
    "consent_expired": {"can_resend": True},
    "case_selected": {"summary_line": "healthcare claim (denied)"},
    "choose_case": {"options": ["a", "b"]},
    "no_hints": {"options": ["a"]},
    "no_match": {"options": ["a"]},
    "answer_question": {"question": "?", "followup": {"kind": "fallback", "text": "Fallback."}},
    "deadline_passed": {"deadline": "2026-03-18"},
    "docs_exhausted": {"text": "A human will review."},
    "offer_email": {"to_masked": "m*****@email.com"},
    "email_preview": {
        "draft": {"subject": "Summary", "to_masked": "m*****@email.com", "sections": {"A": ["x"]}}
    },
    "email_sent": {"message_id": "MSG-1", "to_masked": "m*****@email.com"},
    "email_address_restricted": {"to_masked": "m*****@email.com"},
    "decline_off_topic": {"offer_handoff": True},
    "answer_general": {"kb": {"default_guidance": "Send documents."}, "question": "?"},
    "session_closed": {"phase": "CLOSED"},
}


def _rctx(directives: list[Directive], facts: dict[str, Any] | None = None) -> ResponderContext:
    return ResponderContext(
        phase=Phase.VERIFY_ID,
        directives=directives,
        facts=facts or {},
        user_text="",
        history=[],
        tool_executor=None,
        whitelist_text="",
    )


@pytest.mark.parametrize("kind", get_args(DirectiveKind))
def test_every_directive_kind_renders(kind: DirectiveKind) -> None:
    for data in (MINIMAL_DATA.get(kind, {}), {}):
        d = Directive(kind=kind, data=data)
        assert render([d], _rctx([d])).strip()


def test_verify_failed_exact_sentence() -> None:
    d = Directive(kind="verify_failed", data={"options": ["email", "id_last4"]})
    text = render([d], _rctx([d]))
    assert text.startswith(
        "I wasn't able to verify with that information — please double-check or add another detail."
    )
    assert "email address" in text


def test_need_identity_counts_and_greeting() -> None:
    d = Directive(kind="need_identity", data={"needed": 2, "options": ["dob", "phone"]})
    assert "To protect your information I need 2 more of:" in render([d], _rctx([d]))
    g = Directive(
        kind="need_identity",
        data={
            "needed": 3,
            "options": ["full_name", "dob", "phone", "email", "id_last4"],
            "greeting": True,
        },
    )
    text = render([g], _rctx([g]))
    assert "any three" in text and "date of birth" in text


def test_directives_render_in_order() -> None:
    ds = [Directive(kind="confirm_verified"), Directive(kind="anything_else")]
    text = render(ds, _rctx(ds))
    assert text.index("verified") < text.index("anything else")


def test_answer_denial_from_claim_facts() -> None:
    facts = {
        "claim": {
            "case_id": "CL-1",
            "status": "denied",
            "summary": "Denied",
            "denial_reason": "the file lacked the X report",
            "documents_needed": ["X report"],
        },
        "turn_intent": "denial_question",
    }
    d = Directive(
        kind="answer_question", data={"followup": {"kind": "fallback", "text": "generic"}}
    )
    text = render([d], _rctx([d], facts))
    assert "Claim CL-1 was denied because the file lacked the X report." in text
    assert "the X report" in text.split("because")[1]


def test_decline_off_topic_pulls_back_to_step() -> None:
    d = Directive(kind="decline_off_topic", data={"offer_handoff": False})
    text = render([d], _rctx([d]))
    assert "I can only help with insurance claims and policy questions." in text
    assert "verify" in text.lower()


def test_email_preview_shows_subject_and_body() -> None:
    draft = {"subject": "Your summary", "to_masked": "m***", "sections": {"Next steps": ["Call"]}}
    d = Directive(kind="email_preview", data={"draft": draft})
    text = render([d], _rctx([d]))
    assert "Your summary" in text and "- Call" in text and "\n\n" in text


def test_offer_email_acknowledges_pending_handoff() -> None:
    d = Directive(
        kind="offer_email", data={"to_masked": "m*****@email.com", "handoff_pending": True}
    )
    text = render([d], _rctx([d]))
    assert text.startswith("I'll connect you with a representative.")
    assert "m*****@email.com" in text
