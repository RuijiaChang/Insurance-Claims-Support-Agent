from datetime import date
from pathlib import Path

import pytest

from app.settings import Settings, load_sop_config, today


def test_sop_config_values() -> None:
    sop = load_sop_config(Settings().sop_config_path)
    assert sop.verification.min_matched_fields == 3
    assert sop.verification.max_failures == 3
    assert sop.verification.name_fuzzy_threshold == 90
    assert sop.scope.off_topic_offer_human_after == 3
    assert sop.emotion.persuasion_budget == 2
    assert sop.emotion.escalate_streak == 3
    assert sop.consent.poll_interval_sec == 4
    assert sop.consent.max_resends == 1
    assert sop.process.max_tool_iterations == 3
    assert sop.process.doc_fuzzy_threshold == 85
    assert sop.process.max_hops == 3
    assert sop.ratelimit.per_ip_per_min == 20
    assert sop.ratelimit.per_ip_per_day == 300
    assert sop.ratelimit.global_per_day == 3000
    assert sop.ratelimit.max_turns_per_session == 60
    assert sop.session.ttl_min == 120
    assert sop.session.max_text_len == 4000


def test_today_uses_demo_today() -> None:
    assert today(Settings(demo_today=date(2026, 3, 5))) == date(2026, 3, 5)
    assert today(Settings(demo_today=None)) == date.today()


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEMO_TODAY", "2026-03-05")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path))
    s = Settings()
    assert s.demo_today == date(2026, 3, 5)
    assert s.llm_provider == "deepseek"
    assert s.outbox_dir == tmp_path
