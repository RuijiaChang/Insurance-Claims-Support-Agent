import pytest

from app.data.repo import Claim, FixtureRepo
from app.tools.claims import CaseHintsInput, claim_summary_line, resolve_case, score_cases


@pytest.fixture
def claims(repo: FixtureRepo) -> list[Claim]:
    return repo.claims_for("P9")


def _by_id(claims: list[Claim], case_id: str) -> Claim:
    return next(c for c in claims if c.case_id == case_id)


def test_scores_margaret_hint(claims: list[Claim]) -> None:
    hints = CaseHintsInput(case_type="healthcare", status="denied", month=1)
    scores = {c.case_id: s for c, s in score_cases(claims, hints)}
    assert scores["CL-2048"] == 8
    assert scores["CL-2011"] == 5


def test_resolve_unique_margaret(claims: list[Claim]) -> None:
    hints = CaseHintsInput(case_type="healthcare", status="denied", month=1)
    out = resolve_case(claims, hints)
    assert out.kind == "unique"
    assert out.case is not None and out.case.case_id == "CL-2048"


def test_resolve_ambiguous_without_status(claims: list[Claim]) -> None:
    out = resolve_case(claims, CaseHintsInput(case_type="healthcare", month=1))
    assert out.kind == "ambiguous"
    assert {c.case_id for c in out.candidates} == {"CL-2048", "CL-2011"}


def test_resolve_case_id_exact(claims: list[Claim]) -> None:
    out = resolve_case(claims, CaseHintsInput(case_id="cl-2102"))
    assert out.kind == "unique"
    assert out.case is not None and out.case.case_id == "CL-2102"


def test_resolve_auto_only(claims: list[Claim]) -> None:
    out = resolve_case(claims, CaseHintsInput(case_type="AUTO"))
    assert out.kind == "unique"
    assert out.case is not None and out.case.case_id == "CL-2102"


def test_resolve_no_hints(claims: list[Claim]) -> None:
    hints = CaseHintsInput()
    assert hints.is_empty()
    out = resolve_case(claims, hints)
    assert out.kind == "no_hints"
    assert [c.case_id for c in out.candidates] == [c.case_id for c in claims]
    assert len(out.candidates) == 4


def test_resolve_no_match(claims: list[Claim]) -> None:
    out = resolve_case(claims, CaseHintsInput(case_type="life"))
    assert out.kind == "no_match"
    assert len(out.candidates) == 4


def test_resolve_no_claims() -> None:
    out = resolve_case([], CaseHintsInput(case_type="auto"))
    assert out.kind == "no_claims"
    assert out.case is None and out.candidates == []


def test_score_sort_is_stable_for_ties(claims: list[Claim]) -> None:
    ranked = score_cases(claims, CaseHintsInput())
    assert [c.case_id for c, _ in ranked] == [c.case_id for c in claims]


def test_summary_line_has_no_amounts(claims: list[Claim]) -> None:
    line = claim_summary_line(_by_id(claims, "CL-2048"))
    assert line == "healthcare claim from Jan 12, 2026 (denied)"
