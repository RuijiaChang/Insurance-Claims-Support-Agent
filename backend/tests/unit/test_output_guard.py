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


def test_leak_unformatted_amounts(repo: FixtureRepo) -> None:
    s = _state(False, Phase.VERIFY_ID)
    for text in ("Your max is $1450.", "That is 1450 dollars."):
        assert "leak:amount" in check_reply(text, s, _rctx(), repo).violations


def test_user_typed_superstring_does_not_exempt(repo: FixtureRepo) -> None:
    s = _state(False, Phase.VERIFY_ID)
    r = check_reply("It is 1450.00.", s, _rctx(user_text="21450.00"), repo)
    assert "leak:amount" in r.violations


def test_date_formats_grounding(repo: FixtureRepo) -> None:
    s = _state(True)
    for text in ("18 April 2026", "1 April", "3/19/2026", "april 1", "3/18/2025"):
        r = check_reply(f"Due {text}.", s, _rctx(facts=FACTS), repo)
        assert any(v.startswith("ungrounded_date") for v in r.violations), text
    for text in ("18 March 2026", "3/18/2026", "3/18/26", "18 Mar"):
        assert check_reply(f"Due {text}.", s, _rctx(facts=FACTS), repo).ok, text


def test_case_id_whole_match(repo: FixtureRepo) -> None:
    s = _state(True)
    assert check_reply("CL-20", s, _rctx(facts=FACTS), repo).violations == [
        "ungrounded_case_id:CL-20"
    ]
    assert not check_reply("CL-204", s, _rctx(facts=FACTS), repo).ok
    assert check_reply("CL-2048", s, _rctx(facts=FACTS), repo).ok


def test_amount_whitelist_ignores_date_and_id_digits(repo: FixtureRepo) -> None:
    s = _state(True)
    assert not check_reply("It is $18.", s, _rctx(facts=FACTS), repo).ok
    assert not check_reply("It is $2048.", s, _rctx(facts=FACTS), repo).ok
    assert check_reply("It is $1,450.", s, _rctx(facts=FACTS), repo).ok


def test_ssn_space_separated(repo: FixtureRepo) -> None:
    r = check_reply("SSN 123 45 6789", _state(True), _rctx(facts=FACTS), repo)
    assert "pii_echo:ssn" in r.violations


def test_pre_access_normalized_record_dates_and_amounts(repo: FixtureRepo) -> None:
    state = _state(False, Phase.VERIFY_ID)
    for text in ("18 March 2026", "3/18/2026", "Mar 18, 2026", "1450.0", "15 March 1985"):
        assert not check_reply(text, state, _rctx(Phase.VERIFY_ID), repo).ok, text
    assert check_reply(
        "18 March 2026", state, _rctx(Phase.VERIFY_ID, user_text="My deadline is 2026-03-18"), repo
    ).ok


def _with(rctx: ResponderContext, kind: str, **data: object) -> ResponderContext:
    from app.sop.plan import Directive

    rctx.directives.append(Directive(kind=kind, data=data))
    return rctx


def test_off_topic_handoff_offer_must_be_said(repo: FixtureRepo) -> None:
    # Live gpt-4.1-mini dropped the offer and only the quick-reply button carried it.
    s = _state(True, Phase.PROCESS_CASE)
    rctx = _with(_rctx(), "decline_off_topic", offer_handoff=True)
    bad = check_reply("I'm here to help with insurance claims. What else?", s, rctx, repo)
    assert bad.violations == ["missing_handoff_offer"]
    good = "I can only help with claims. I can also connect you with a representative."
    assert check_reply(good, s, rctx, repo).ok
    plain = _with(_rctx(), "decline_off_topic", offer_handoff=False)
    assert check_reply("I can only help with claims.", s, plain, repo).ok


def test_email_offer_before_handoff_must_acknowledge_it(repo: FixtureRepo) -> None:
    s = _state(True, Phase.POST_PROCESS)
    rctx = _with(
        _rctx(Phase.POST_PROCESS), "offer_email", to_masked="m*****@x.com", handoff_pending=True
    )
    assert not check_reply("Want a summary at m*****@x.com?", s, rctx, repo).ok
    assert check_reply(
        "I'll connect you with a representative. Want a summary at m*****@x.com first?",
        s,
        rctx,
        repo,
    ).ok
