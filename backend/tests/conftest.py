import pytest

from app.data.repo import FixtureRepo, load_repo
from app.settings import Settings


@pytest.fixture(scope="session")
def repo() -> FixtureRepo:
    return load_repo(Settings().fixtures_dir)
