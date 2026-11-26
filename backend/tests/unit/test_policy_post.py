import pytest

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.email_summary import build_email_draft
from app.sop.extraction import Extraction
from app.sop.memory import apply_extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import StepResult
from app.sop.policies.post import handle_post
from app.sop.state import CaseLogEntry, PendingQuestion, SessionState
from app.tools.email import Outbox
from tests.fakes import apply_step, ex, make_ctx

HOLDER_EMAIL = "m*****@email.com"


def _state() -> SessionState:
    s = SessionState.new("s1")
    s.phase = Phase.POST_PROCESS
    s.sub_state = SubState.OFFER
    s.verified_party_id = "P9"
    s.access_granted = True
    s.active_case_id = "CL-2048"
    s.discussed_case_ids = ["CL-2048"]
    s.case_log = [
        CaseLogEntry(case_id="CL-2048", kind="fact", text="Status: denied"),
        CaseLogEntry(case_id="CL-2048", kind="next_step", text="Submit the pathology report"),
        CaseLogEntry(case_id="CL-2048", kind="deadline", text="Appeal deadline: 2026-03-18"),
    ]
    return s


def _turn(
    state: SessionState,
    repo: FixtureRepo,
    sop: SopConfig,
    extraction: Extraction | None = None,
    outbox: Outbox | None = None,
    **ctx_kw: object,
) -> StepResult:
    extraction = extraction or ex()
    apply_extraction(state, extraction, 5)
    ctx = make_ctx(repo, sop, turn=5, **ctx_kw)  # type: ignore[arg-type]
    if outbox is not None:
        ctx.outbox = outbox
    step = handle_post(state, extraction, ctx)
    apply_step(state, step)
    return step


def _kinds(step: StepResult) -> list[str]:
    return [d.kind for d in step.directives]


def _holder_email(repo: FixtureRepo) -> str:
    return repo.holder("P9").email


def test_offer_masks_email(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    step = _turn(s, repo, sop)
    assert _kinds(step) == ["offer_email"]
    assert step.directives[0].data["to_masked"] == HOLDER_EMAIL
    assert step.directives[0].data["preference"] is None
    assert [(q.label, q.action) for q in step.quick_replies] == [
        ("Send summary", "email_send"),
        ("No thanks", "email_skip"),
    ]
    assert s.pending_question == PendingQuestion(kind="offer_email")
    assert (s.phase, s.sub_state) == (Phase.POST_PROCESS, SubState.OFFER)


def test_offer_includes_memory_preference(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.memory.set("email_preference", "send me an email", 1, Phase.VERIFY_ID)
    step = _turn(s, repo, sop)
    assert step.directives[0].data["preference"] == "send me an email"


def test_preview_then_send_closes(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    outbox = Outbox(None)
    _turn(s, repo, sop, outbox=outbox)
    step = _turn(s, repo, sop, action="email_send", outbox=outbox)
    assert _kinds(step) == ["email_preview"]
    assert step.fact_scope == "email"
    assert s.sub_state == SubState.PREVIEW
    assert s.email.preview is not None
    assert s.pending_question == PendingQuestion(kind="confirm_send")
    assert [(q.label, q.action) for q in step.quick_replies] == [
        ("Send", "email_confirm"),
        ("Skip", "email_skip"),
    ]
    assert outbox.list("s1") == []
    step = _turn(s, repo, sop, action="email_confirm", outbox=outbox)
    assert _kinds(step) == ["email_sent", "closing"]
    assert step.directives[0].data["to_masked"] == HOLDER_EMAIL
    assert s.email.decision == "send"
    assert (s.phase, s.sub_state) == (Phase.CLOSED, SubState.NONE)
    sent = outbox.list("s1")
    assert len(sent) == 1
    assert sent[0]["to"] == _holder_email(repo)
    assert s.email.sent_message_id == sent[0]["message_id"]
    assert s.pending_question is None


def test_affirm_after_offer_previews(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop)
    step = _turn(s, repo, sop, ex(acts=["affirm"]))
    assert _kinds(step) == ["email_preview"]


def test_affirm_in_preview_sends(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    outbox = Outbox(None)
    _turn(s, repo, sop, outbox=outbox)
    _turn(s, repo, sop, action="email_send", outbox=outbox)
    _turn(s, repo, sop, ex(acts=["affirm"]), outbox=outbox)
    assert len(outbox.list("s1")) == 1


def test_skip_closes_empty_outbox(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    outbox = Outbox(None)
    _turn(s, repo, sop, outbox=outbox)
    step = _turn(s, repo, sop, ex(acts=["deny"]), outbox=outbox)
    assert _kinds(step) == ["email_skipped", "closing"]
    assert s.email.decision == "skip"
    assert (s.phase, s.sub_state) == (Phase.CLOSED, SubState.NONE)
    assert outbox.list("s1") == []


def test_skip_from_preview(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop)
    _turn(s, repo, sop, action="email_send")
    _turn(s, repo, sop, action="email_skip")
    assert s.email.decision == "skip"
    assert s.phase == Phase.CLOSED


def test_pending_handoff_after_email(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.pending_handoff = "user_request"
    _turn(s, repo, sop)
    step = _turn(s, repo, sop, action="email_skip")
    assert _kinds(step) == ["email_skipped", "handoff_done"]
    assert (s.phase, s.sub_state) == (Phase.HANDOFF, SubState.NONE)
    assert s.handoff is not None
    assert s.handoff.reason == "user_request"
    assert s.handoff.case_id == "CL-2048"


def test_draft_covers_two_cases(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.discussed_case_ids = ["CL-2048", "CL-2102"]
    s.case_log.append(CaseLogEntry(case_id="CL-2102", kind="fact", text="Status: approved"))
    draft = build_email_draft(s, repo)
    assert list(draft.sections) == [
        "What we discussed",
        "Claim status / outcome",
        "Next steps",
        "How to reach us",
    ]
    assert draft.subject == "Summary of your claims support conversation"
    assert draft.to_masked == HOLDER_EMAIL
    discussed = draft.sections["What we discussed"]
    assert len(discussed) == 2
    assert discussed[0].startswith("CL-2048: ")
    assert discussed[1].startswith("CL-2102: ")
    assert "CL-2102: Status: approved" in draft.sections["Claim status / outcome"]
    assert draft.sections["Next steps"] == [
        "CL-2048: Submit the pathology report",
        "CL-2048: Appeal deadline: 2026-03-18",
    ]


def test_draft_defaults_when_nothing_discussed(repo: FixtureRepo) -> None:
    s = _state()
    s.discussed_case_ids = []
    s.case_log = []
    draft = build_email_draft(s, repo)
    assert draft.sections["What we discussed"] == [
        "General questions about your policy and claims."
    ]
    assert draft.sections["Next steps"] == ["No further action is needed right now."]


def test_draft_requires_access(repo: FixtureRepo) -> None:
    s = _state()
    s.access_granted = False
    with pytest.raises(ValueError):
        build_email_draft(s, repo)


def test_other_address_restricted(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    outbox = Outbox(None)
    _turn(s, repo, sop, outbox=outbox)
    step = _turn(s, repo, sop, user_text="send it to bob@evil.com instead", outbox=outbox)
    assert _kinds(step) == ["email_address_restricted"]
    assert step.directives[0].data["to_masked"] == HOLDER_EMAIL
    assert [q.action for q in step.quick_replies] == ["email_send", "email_skip"]
    assert (s.phase, s.sub_state) == (Phase.POST_PROCESS, SubState.OFFER)
    assert outbox.list("s1") == []


def test_own_address_is_not_restricted(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop)
    step = _turn(s, repo, sop, user_text=f"yes to {_holder_email(repo).upper()}")
    assert "email_address_restricted" not in _kinds(step)


def test_question_returns_to_process(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop)
    step = _turn(s, repo, sop, ex(acts=["ask_question"], question="one more thing?"))
    assert step.continue_hop is True
    assert (s.phase, s.sub_state) == (Phase.PROCESS_CASE, SubState.ACTIVE)
    assert s.pending_question is None


def test_unclear_reply_reemits_prompt(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    _turn(s, repo, sop)
    step = _turn(s, repo, sop, user_text="hmm")
    assert _kinds(step) == ["offer_email"]
    assert len(step.quick_replies) == 2


def test_post_without_verified_holder_raises_explicit_error(
    repo: FixtureRepo, sop: SopConfig
) -> None:
    # An explicit check, not an `assert`: it must hold even under `python -O`.
    s = _state()
    s.verified_party_id = None
    with pytest.raises(RuntimeError, match="verified"):
        _turn(s, repo, sop)


def test_confirm_without_preview_raises_explicit_error(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.pending_question = PendingQuestion(kind="confirm_send")
    s.email.preview = None
    with pytest.raises(RuntimeError, match="preview"):
        _turn(s, repo, sop, action="email_confirm")
