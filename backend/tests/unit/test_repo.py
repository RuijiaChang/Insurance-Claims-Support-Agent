from datetime import date
from pathlib import Path

import pytest

from app.data.repo import FixtureRepo, load_repo
from app.settings import Settings


@pytest.fixture(scope="module")
def repo() -> FixtureRepo:
    return load_repo(Settings().fixtures_dir)


def test_repo_loads_counts(repo: FixtureRepo) -> None:
    assert len(repo.policyholders) == 4
    assert len(repo.claims) == 5
    assert len(repo.representatives) == 1
    assert repo.consent_scenarios["default"] == ["pending", "approved"]
    assert len(repo.consent_scenarios["timeout"]) == 5


def test_default_fixtures_dir_exists() -> None:
    assert Settings().fixtures_dir.joinpath("claims.json").is_file()
    assert isinstance(Settings().fixtures_dir, Path)


def test_claims_for_p9(repo: FixtureRepo) -> None:
    assert {c.case_id for c in repo.claims_for("P9")} == {
        "CL-2048",
        "CL-2011",
        "CL-1899",
        "CL-2102",
    }
    assert repo.claims_for("P7") == []


def test_holder_lookup(repo: FixtureRepo) -> None:
    assert repo.holder("P9").name == "Margaret Chen"


def test_claim_optional_fields(repo: FixtureRepo) -> None:
    by_id = {c.case_id: c for c in repo.claims}
    assert by_id["CL-2102"].documents_needed == []
    assert by_id["CL-2102"].appeal_deadline is None
    assert by_id["CL-2048"].appeal_deadline == date(2026, 3, 18)
