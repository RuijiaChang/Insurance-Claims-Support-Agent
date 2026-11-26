from pathlib import Path

from app.sop.email_summary import EmailDraft
from app.tools.consent import ConsentState, poll_consent, request_consent, resend_consent
from app.tools.email import Outbox, mask_email, mask_phone
from app.tools.handoff import create_ticket

SEQS = {"default": ["pending", "approved"], "timeout": ["pending"] * 5}


def test_default_sequence() -> None:
    c = request_consent(ConsentState())
    assert c.status == "pending" and c.polls == 0
    assert c.request_id is not None and c.request_id.startswith("CR-")
    c1 = poll_consent(c, SEQS)
    assert c1.status == "pending"
    c2 = poll_consent(c1, SEQS)
    assert c2.status == "approved"
    assert poll_consent(c2, SEQS) == c2
    assert c.polls == 0  # input not mutated


def test_poll_not_requested_unchanged() -> None:
    c = ConsentState()
    assert poll_consent(c, SEQS) == c


def test_timeout_expires_after_sequence() -> None:
    c = request_consent(ConsentState(scenario="timeout"))
    for _ in range(4):
        c = poll_consent(c, SEQS)
        assert c.status == "pending"
    c = poll_consent(c, SEQS)
    assert c.status == "expired"
    assert poll_consent(c, SEQS) == c


def test_resend_limit() -> None:
    c = poll_consent(request_consent(ConsentState()), SEQS)
    r = resend_consent(c, 1)
    assert r is not None and r.polls == 0 and r.resends == 1
    assert resend_consent(r, 1) is None


def _draft() -> EmailDraft:
    return EmailDraft(
        subject="Your claim summary",
        to_masked="m*****@email.com",
        sections={"Discussed": ["a", "b"], "Next steps": ["c"]},
    )


def test_draft_body() -> None:
    assert _draft().body == "Discussed\n- a\n- b\n\nNext steps\n- c"


def test_outbox_send_and_list(tmp_path: Path) -> None:
    box = Outbox(tmp_path)
    mid = box.send("s1", "margaret@email.com", _draft())
    items = box.list("s1")
    assert items == [
        {
            "message_id": mid,
            "to": "margaret@email.com",
            "subject": "Your claim summary",
            "body": _draft().body,
        }
    ]
    assert mid.startswith("MSG-")
    files = list(tmp_path.glob("*.eml"))
    assert [f.name for f in files] == [f"s1-{mid}.eml"]
    assert "claims-support@example.com" in files[0].read_text()
    assert box.list("other") == []


def test_outbox_memory_only() -> None:
    box = Outbox(None)
    box.send("s", "a@b.com", _draft())
    assert len(box.list("s")) == 1


def test_masks() -> None:
    assert mask_email("margaret@email.com") == "m*****@email.com"
    assert mask_phone("+16505212836") == "***-***-**36"


def test_ticket_hides_case_without_access() -> None:
    t = create_ticket("locked", False, False, "claim status", "CL-2048", 4)
    assert t.case_id is None
    assert t.ticket_id.startswith("HT-") and len(t.ticket_id) == 9
    t2 = create_ticket("user_request", True, True, None, "CL-2048", 5)
    assert t2.case_id == "CL-2048" and t2.created_turn == 5
