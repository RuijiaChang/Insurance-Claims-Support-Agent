from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

_APP_DIR = Path(__file__).resolve().parent
_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


class Settings(BaseSettings):
    """Runtime settings, read from environment variables (field name, case-insensitive)."""

    openai_api_key: str | None = None
    llm_provider: Literal["openai", "deepseek", "custom"] = "openai"
    openai_base_url: str | None = None
    openai_model: str | None = None
    demo_today: date | None = None
    fixtures_dir: Path = Path(__file__).resolve().parents[2] / "apps/insurance_claims/fixtures"
    outbox_dir: Path | None = None
    log_level: str = "INFO"
    sop_config_path: Path = _APP_DIR / "config" / "sop.yaml"

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "outbox_dir",
        "demo_today",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        # `.env.example` ships blank values such as `OPENAI_BASE_URL=`; treat them as unset.
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}")
        return level

    frontend_dir: Path = Path(__file__).resolve().parents[2] / "frontend/dist"
    # With one trusted proxy, key rate limits on the rightmost X-Forwarded-For entry.
    trust_proxy: bool = False


class VerificationConfig(BaseModel):
    min_matched_fields: int
    max_failures: int
    name_fuzzy_threshold: int


class ScopeConfig(BaseModel):
    off_topic_offer_human_after: int


class EmotionConfig(BaseModel):
    persuasion_budget: int
    escalate_streak: int


class ConsentConfig(BaseModel):
    poll_interval_sec: int
    max_resends: int


class ProcessConfig(BaseModel):
    max_tool_iterations: int
    doc_fuzzy_threshold: int
    max_hops: int


class RateLimitConfig(BaseModel):
    per_ip_per_min: int
    per_ip_per_day: int
    global_per_day: int
    max_turns_per_session: int


class SessionConfig(BaseModel):
    ttl_min: int
    max_text_len: int


class SopConfig(BaseModel):
    verification: VerificationConfig
    scope: ScopeConfig
    emotion: EmotionConfig
    consent: ConsentConfig
    process: ProcessConfig
    ratelimit: RateLimitConfig
    session: SessionConfig


def load_sop_config(path: Path) -> SopConfig:
    with path.open(encoding="utf-8") as f:
        return SopConfig.model_validate(yaml.safe_load(f))


def today(settings: Settings) -> date:
    """The demo's notion of 'today': DEMO_TODAY if set, else the real date."""
    return settings.demo_today or date.today()


@lru_cache
def get_settings() -> Settings:
    return Settings()
