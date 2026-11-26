import pytest

from app.data.repo import FixtureRepo, load_repo
from app.settings import Settings, SopConfig, load_sop_config


@pytest.fixture(scope="session")
def repo() -> FixtureRepo:
    return load_repo(Settings().fixtures_dir)


@pytest.fixture(scope="session")
def sop() -> SopConfig:
    return load_sop_config(Settings().sop_config_path)
