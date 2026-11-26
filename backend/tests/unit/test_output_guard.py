from app.data.repo import FixtureRepo
from app.guards.output_guard import check_reply, sensitive_terms
from app.sop.context import ResponderContext
from app.sop.phases import Phase
from app.sop.state import Message, SessionState


def _rctx(
    phase: Phase = Phase.PROCESS_CASE,
    facts: str = "",
    user_text: str = "",
) -> ResponderContext:
    return ResponderContext(
        phase=phase,
        directives=[],
        facts={},
        user_text=user_text,
        history=[],
        tool_executor=None,
        whitelist_text=facts + "\n" + user_text,
    )


def _state(access: bool, phase: Phase = Phase.PROCESS_CASE, *user_msgs: str) -> SessionState:
    s = SessionState.new("s1")
    s.access_granted = access
    s.phase = phase
    for i, m in enumerate(user_msgs):
        s.transcript.append(Message(role="user", text=m, turn=i))
    return s


FACTS = '{"allowed_max_amount": "1450.00", "appeal_deadline": "2026-03-18", "case_id": "CL-2048"}'


def test_sensitive_terms_forms(repo: FixtureRepo) -> None:
    terms = sensitive_terms(repo)
    assert {"CL-2048", "1450.00", "1,450", "$1,450", "$1,450.00"} <= terms
    assert {"2026-03-18", "March 18, 2026", "2026-01-12", "January 12, 2026"} <= terms
    assert {"+16505212836", "margaret@email.com", "1985-03-15"} <= terms
    assert "pathology report" in terms
    assert "0.00" not in terms


def test_leak_case_id_pre_access(repo: FixtureRepo) -> None:
    r = check_reply("Your claim CL-2048 is ready.", _state(False, Phase.VERIFY_ID), _rctx(), repo)
    assert not r.ok
    assert "leak:CL-2048" in r.violations


def test_no_leak_check_after_access(repo: FixtureRepo) -> None:
    r = check_reply("Claim CL-2048.", _state(True), _rctx(facts=FACTS), repo)
    assert r.ok


def test_user_words_not_leak(repo: FixtureRepo) -> None:
    s = _state(False, Phase.VERIFY_ID, "my claim was Denied")
    r = check_reply("I'm sorry it was denied.", s, _rctx(), repo)
    assert r.ok
    s2 = _state(False, Phase.VERIFY_ID)
    r2 = check_reply(
        "It was the review file did not include the pathology report and the treating "
        "provider office note.",
        s2,
        _rctx(user_text=""),
        repo,
    )
    assert not r2.ok
    # user typed the case id themselves: exempt
    r3 = check_reply("About CL-2048, please verify.", s2, _rctx(user_text="cl-2048"), repo)
    assert r3.ok


def test_leak_amount_and_date_whole_token(repo: FixtureRepo) -> None:
    s = _state(False, Phase.VERIFY_ID)
    r = check_reply("Max is $1,450 and the deadline is March 18, 2026.", s, _rctx(), repo)
    assert "leak:amount" in r.violations and "leak:date" in r.violations
    assert check_reply("Reference 21450.00 is unrelated.", s, _rctx(), repo).ok


def test_amount_normalization_ok(repo: FixtureRepo) -> None:
    r = check_reply("The cap is $1,450.", _state(True), _rctx(facts=FACTS), repo)
    assert r.ok


def test_ungrounded_amount_flagged(repo: FixtureRepo) -> None:
    r = check_reply("You will get $999.", _state(True), _rctx(facts=FACTS), repo)
    assert not r.ok
    assert "ungrounded_amount:$999" in r.violations
    r2 = check_reply("About 500 dollars.", _state(True), _rctx(facts=FACTS), repo)
    assert not r2.ok


def test_grounding_only_in_process_phases(repo: FixtureRepo) -> None:
    s = _state(True, Phase.RESOLVE_INTENT)
    assert check_reply("It costs $999.", s, _rctx(Phase.RESOLVE_INTENT), repo).ok
    s2 = _state(True, Phase.POST_PROCESS)
    assert not check_reply("It costs $999.", s2, _rctx(Phase.POST_PROCESS), repo).ok


def test_date_normalization_ok(repo: FixtureRepo) -> None:
    s = _state(True)
    assert check_reply("Deadline is March 18, 2026.", s, _rctx(facts=FACTS), repo).ok
    assert check_reply("Deadline is Mar 18.", s, _rctx(facts=FACTS), repo).ok
    assert check_reply("Deadline is 2026-03-18.", s, _rctx(facts=FACTS), repo).ok
    r = check_reply("Deadline is April 1.", s, _rctx(facts=FACTS), repo)
    assert "ungrounded_date:April 1" in r.violations
    r2 = check_reply("Deadline is March 18, 2025.", s, _rctx(facts=FACTS), repo)
    assert not r2.ok


def test_whitelist_month_name_dates(repo: FixtureRepo) -> None:
    facts = "You said Jan 12, 2026 for the claim."
    assert check_reply("On January 12, 2026.", _state(True), _rctx(facts=facts), repo).ok


def test_ungrounded_case_id(repo: FixtureRepo) -> None:
    r = check_reply("See CL-9999 and CL-2048.", _state(True), _rctx(facts=FACTS), repo)
    assert r.violations == ["ungrounded_case_id:CL-9999"]


def test_pii_echo_flagged(repo: FixtureRepo) -> None:
    s = _state(True)
    r = check_reply("Call +16505212836.", s, _rctx(facts=FACTS), repo)
    assert "pii_echo:phone" in r.violations
    assert not check_reply("Call (650) 521-2836.", s, _rctx(facts=FACTS), repo).ok
    assert check_reply("Sent to m*****@email.com, ***-***-**36.", s, _rctx(facts=FACTS), repo).ok


def test_pii_echo_ssn_and_email_always(repo: FixtureRepo) -> None:
    s = _state(False, Phase.VERIFY_ID)
    assert "pii_echo:ssn" in check_reply("SSN 123-45-6789", s, _rctx(), repo).violations
    assert "pii_echo:ssn" in check_reply("SSN 123456789", s, _rctx(), repo).violations
    r = check_reply("Mail margaret@email.com", _state(True), _rctx(facts=FACTS), repo)
    assert "pii_echo:email" in r.violations
    assert all("margaret" not in v and "650" not in v for v in r.violations)
