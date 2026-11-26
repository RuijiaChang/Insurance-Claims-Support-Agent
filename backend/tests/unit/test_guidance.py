from datetime import date
from typing import Any

import pytest

from app.data.repo import Claim, FixtureRepo
from app.tools.guidance import (
    canonical_doc,
    deadline_fact,
    docs_exhausted_text,
    document_alternatives,
    document_requirements,
    documents_phrase,
    field_definition,
    kb_general,
    match_followup,
)


def _claim(repo: FixtureRepo, case_id: str) -> Claim:
    return next(c for c in repo.claims if c.case_id == case_id)


@pytest.fixture
def c48(repo: FixtureRepo) -> Claim:
    return _claim(repo, "CL-2048")


@pytest.fixture
def c02(repo: FixtureRepo) -> Claim:
    return _claim(repo, "CL-2102")


def test_submission_timing_wins_longest_phrase(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "How soon do I need to submit?", "denial_question", None)
    assert r.kind == "matched"
    assert r.topic == "submission_timing"
    assert (
        r.text
        == "For claim CL-2048, please submit the pathology report and the office note within a week."
    )


def test_canonical_doc(repo: FixtureRepo) -> None:
    keys = list(repo.guideline["document_guidance"])
    assert canonical_doc("pathology report", keys, 85) == "original pathology report"
    assert canonical_doc("office note", keys, 85) == "treating provider office note"
    assert canonical_doc("diagnosis report", keys, 85) is None


def test_documents_phrase() -> None:
    assert documents_phrase([]) == ""
    assert documents_phrase(["diagnosis report"]) == "the diagnosis report"
    assert documents_phrase(["pathology report", "office note"]) == (
        "the pathology report and the office note"
    )
    assert documents_phrase(["a", "b", "c"]) == "the a, the b, and the c"


def test_submission_method_not_filtered_by_session_intent(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "how do I submit them?", "denial_question", None)
    assert r.topic == "submission_method"


def test_processing_time(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "how long does it take after I submit", None, None)
    assert r.topic == "processing_time_after_submission"
    assert r.text is not None
    assert "usually less than a week" in r.text


def test_file_format(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "can I send a scan or pdf?", None, None)
    assert r.topic == "file_format_requirements"


def test_receipt(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "will I get confirmation?", None, None)
    assert r.topic == "receipt_confirmation"


def test_ago_excluded(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "how long ago was it denied?", None, None)
    assert r.kind == "fallback"


def test_ago_excluded_checks_every_occurrence(repo: FixtureRepo, c48: Claim) -> None:
    q = "how long ago was it denied, and how long will it take?"
    r = match_followup(repo, c48, q, None, None)
    assert r.topic == "processing_time_after_submission"


def test_topic_from_llm(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(
        repo, c48, "I can't find the report", None, "missing_required_material_alternatives"
    )
    assert r.kind == "matched"
    assert r.text is not None
    assert "CL-2048" in r.text


def test_topic_from_llm_still_needs_documents(repo: FixtureRepo, c02: Claim) -> None:
    r = match_followup(repo, c02, "I can't find it", None, "missing_required_material_alternatives")
    assert r.kind == "no_specific_guidance"


def test_no_documents_case_gets_no_specific_guidance(repo: FixtureRepo, c02: Claim) -> None:
    r = match_followup(repo, c02, "how long will this take", None, None)
    assert r.kind == "no_specific_guidance"
    assert r.text is None


@pytest.mark.parametrize(
    ("question", "topic", "asked"),
    [
        ("how long will this take", None, True),  # keyword of a documents-only entry
        ("I can't find it", "missing_required_material_alternatives", True),  # LLM topic
        ("what's the status?", None, False),
        ("how long ago was it denied", None, False),  # "how long" + "ago" is excluded
    ],
)
def test_no_specific_guidance_flags_guidance_questions(
    repo: FixtureRepo, c02: Claim, question: str, topic: Any, asked: bool
) -> None:
    r = match_followup(repo, c02, question, None, topic)
    assert r.kind == "no_specific_guidance"
    assert r.asked_guidance is asked


def test_matched_and_fallback_never_flag_asked_guidance(repo: FixtureRepo, c48: Claim) -> None:
    assert match_followup(repo, c48, "how long will this take", None, None).asked_guidance is False
    assert match_followup(repo, c48, "hello there", None, None).asked_guidance is False


def test_fallback_text_exact(repo: FixtureRepo, c48: Claim) -> None:
    r = match_followup(repo, c48, "what color is the form", None, None)
    assert r.kind == "fallback"
    assert r.text == repo.guideline["claim_followup_fallback"]["en"]


def test_document_requirements(repo: FixtureRepo, c48: Claim) -> None:
    req = document_requirements(repo, c48, 85)
    dg = repo.guideline["document_guidance"]
    assert set(req.per_document) == {"pathology report", "office note"}
    assert req.per_document["pathology report"] == dg["original pathology report"]["en"]
    assert req.per_document["office note"] == dg["treating provider office note"]["en"]
    assert req.case_type == repo.guideline["case_type_guidance"]["healthcare"]["en"]
    assert req.default == repo.guideline["default_guidance"]["en"]


def test_alternatives(repo: FixtureRepo, c48: Claim) -> None:
    alts = document_alternatives(repo, c48, None, 85)
    assert set(alts) == {"pathology report", "office note", "default"}
    one = document_alternatives(repo, c48, "office note", 85)
    assert set(one) == {"office note", "default"}


def test_deadline(c48: Claim, c02: Claim) -> None:
    f = deadline_fact(c48, date(2026, 3, 5))
    assert f is not None
    assert f.days_left == 13
    assert f.passed is False
    g = deadline_fact(c48, date(2026, 11, 25))
    assert g is not None
    assert g.passed is True
    assert deadline_fact(c02, date(2026, 3, 5)) is None


def test_field_definition(repo: FixtureRepo) -> None:
    d = field_definition(repo, "net_pay")
    assert d is not None
    assert "finalized amount" in d
    assert field_definition(repo, "nope") is None


def test_docs_exhausted_and_kb_general(repo: FixtureRepo) -> None:
    assert docs_exhausted_text(repo).startswith("If the caller still cannot")
    kb = kb_general(repo)
    assert set(kb) == {
        "expected_reimbursement_amount",
        "allowed_max_amount",
        "net_pay",
        "net_fee",
        "default_guidance",
    }
