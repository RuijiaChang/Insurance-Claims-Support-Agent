"""REST API tests (spec §12, S17/S18/S19/S24) with a fake LLM factory."""

import asyncio
import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.ratelimit import SlidingWindowLimiter
from app.api.schemas import MAX_TEXT_LEN
from app.api.sessions import SessionStore
from app.llm.base import LLMBundle, LLMError
from app.llm.client import ProviderConfig
from app.main import create_app
from app.settings import Settings, SopConfig
from app.sop.context import ResponderContext
from app.sop.engine import Engine
from app.sop.templates import render
from tests.fakes import ex, make_bundle
from tests.scenarios.test_scenarios import (
    DAVID_EX,
    DAVID_TEXT,
    MARGARET_OPENER,
    MARGARET_OPENER_EX,
)

SERVER_KEY = "sk-server-secret-0123456789"
USER_KEY = "sk-user-secret-abcdefghij"


class Recorder:
    """Fake ``llm_factory``: records every ProviderConfig, returns a scripted fake bundle."""

    def __init__(self, responder: Any = None) -> None:
        self.cfgs: list[ProviderConfig] = []
        self.script: dict[str, Any] = {
            MARGARET_OPENER: ex(**MARGARET_OPENER_EX),
            DAVID_TEXT: ex(**DAVID_EX),
            "That's all, thanks.": ex(acts=["done"]),
            "My name is Margaret Chen, DOB 1985-03-15.": ex(
                identity={"full_name": "Margaret Chen", "dob": "1985-03-15"},
                acts=["provide_info"],
            ),
        }
        self.responder = responder

    def __call__(self, cfg: ProviderConfig) -> LLMBundle:
        self.cfgs.append(cfg)
        return make_bundle(self.script, responder=self.responder)


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": SERVER_KEY,
        "llm_provider": "openai",
        "openai_model": None,
        "openai_base_url": None,
        "demo_today": date(2026, 3, 5),
        "outbox_dir": None,
        "frontend_dir": Path("/nonexistent-frontend-dist"),
    }
    base.update(kw)
    return Settings(**base)


def _app(recorder: Recorder | None = None, **kw: Any) -> tuple[TestClient, Recorder]:
    app = create_app(_settings(**kw))
    rec = recorder or Recorder()
    app.state.llm_factory = rec
    return TestClient(app, raise_server_exceptions=False), rec


def _new(client: TestClient, scenario: str | None = None) -> str:
    body = {} if scenario is None else {"consent_scenario": scenario}
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 200, r.text
    sid: str = r.json()["session_id"]
    return sid


def _say(client: TestClient, sid: str, text: str, **headers: str) -> httpx.Response:
    return client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=headers)


def _press(client: TestClient, sid: str, action: str) -> httpx.Response:
    return client.post(f"/api/sessions/{sid}/messages", json={"action": action})


# --- wiring / config ----------------------------------------------------------------


def test_create_app_wires_state(tmp_path: Path) -> None:
    app = create_app(_settings(outbox_dir=tmp_path))
    s = app.state
    assert isinstance(s.settings, Settings) and isinstance(s.sop, SopConfig)
    assert s.repo is not None
    assert isinstance(s.engine, Engine)
    assert s.engine.today == date(2026, 3, 5) and s.engine.repo is s.repo
    assert isinstance(s.sessions, SessionStore)
    assert s.sessions.ttl_min == s.sop.session.ttl_min
    assert isinstance(s.limiter, SlidingWindowLimiter)
    assert s.limiter.per_ip_per_min == s.sop.ratelimit.per_ip_per_min
    assert s.limiter.per_ip_per_day == s.sop.ratelimit.per_ip_per_day
    assert s.limiter.global_per_day == s.sop.ratelimit.global_per_day
    assert callable(s.llm_factory)


def test_max_text_len_matches_sop(sop: SopConfig) -> None:
    assert MAX_TEXT_LEN == sop.session.max_text_len


def test_config_with_server_key() -> None:
    client, _ = _app()
    body = client.get("/api/config").json()
    assert body == {
        "has_server_key": True,
        "provider": "openai",
        "model": "gpt-5-mini",
        "demo_today": "2026-03-05",
        "consent_scenarios": ["default", "timeout"],
    }
    assert SERVER_KEY not in client.get("/api/config").text


def test_config_without_server_key() -> None:
    client, _ = _app(openai_api_key=None)
    body = client.get("/api/config").json()
    assert body["has_server_key"] is False
    assert body["provider"] is None and body["model"] is None


# --- sessions -----------------------------------------------------------------------


def test_create_session_greeting_and_snapshot() -> None:
    client, rec = _app()
    r = client.post("/api/sessions", json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["session_id"]) == 32
    assert [m["role"] for m in body["messages"]] == ["agent"]
    assert body["messages"][0]["text"]
    assert body["state"]["phase"] == "VERIFY_ID"
    assert body["state"]["counters"]["turns"] == 0
    assert body["quick_replies"] == []
    assert "suggestions" not in body
    assert rec.cfgs == []  # the greeting never builds an LLM


def test_create_session_unknown_scenario_422() -> None:
    client, _ = _app()
    assert client.post("/api/sessions", json={"consent_scenario": "nope"}).status_code == 422
    r = client.post("/api/sessions", json={"consent_scenario": "timeout"})
    assert r.json()["state"]["consent"]["scenario"] == "timeout"


def test_message_flow_margaret() -> None:
    client, _ = _app()
    sid = _new(client)
    r = _say(client, sid, MARGARET_OPENER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"messages", "state", "quick_replies", "llm_error"}
    assert body["state"]["phase"] == "PROCESS_CASE"
    assert body["state"]["active_case_id"] == "CL-2048"
    assert body["llm_error"] is None
    assert all(set(m) == {"role", "text"} for m in body["messages"])
    assert all(set(q) == {"label", "action"} for q in body["quick_replies"])


def test_s18_empty_and_too_long_422() -> None:
    client, _ = _app()
    sid = _new(client)
    url = f"/api/sessions/{sid}/messages"
    for payload in (
        {"text": ""},
        {"text": "   \n\t "},
        {"text": "x" * (MAX_TEXT_LEN + 1)},
        {},
        {"text": None, "action": None},
    ):
        r = client.post(url, json=payload)
        assert r.status_code == 422, payload
        assert "x" * 100 not in r.text  # the rejected input is never echoed back
    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["counters"]["turns"] == 0
    assert client.post(url, json={"text": "x" * MAX_TEXT_LEN}).status_code == 200


def test_snapshot_pre_access_has_no_matched() -> None:
    client, _ = _app()
    sid = _new(client)
    _say(client, sid, "My name is Margaret Chen, DOB 1985-03-15.")
    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["access_granted"] is False
    statuses = {i["field"]: i["status"] for i in state["identity"]}
    assert "matched" not in statuses.values()
    assert statuses["full_name"] == "provided" and statuses["dob"] == "provided"
    assert "Margaret" not in str(state["identity"]) and "1985" not in str(state)


def test_unknown_session_404() -> None:
    client, _ = _app()
    missing = "0" * 32
    for sid in (missing, "not-a-session-id", "A" * 32, "../" * 3 + "x"):
        for method, path, kw in (
            ("POST", f"/api/sessions/{sid}/messages", {"json": {"text": "hi"}}),
            ("POST", f"/api/sessions/{sid}/events", {"json": {"type": "consent_poll"}}),
            ("GET", f"/api/sessions/{sid}/state", {}),
            ("GET", f"/api/sessions/{sid}/transcript", {}),
            ("GET", f"/api/sessions/{sid}/outbox", {}),
            ("DELETE", f"/api/sessions/{sid}", {}),
        ):
            r = client.request(method, path, **kw)
            assert r.status_code == 404, (method, path)
            if "/" not in sid:
                assert r.json() == {"code": "session_not_found"}


def test_delete_session_then_404() -> None:
    client, _ = _app()
    sid = _new(client)
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.get(f"/api/sessions/{sid}/state").status_code == 404


def test_transcript_has_messages_and_events() -> None:
    client, _ = _app()
    sid = _new(client)
    _say(client, sid, MARGARET_OPENER)
    body = client.get(f"/api/sessions/{sid}/transcript").json()
    assert body["session_id"] == sid
    assert [m["role"] for m in body["transcript"]] == ["agent", "user", "agent"]
    assert {"turn", "stage", "summary"} <= set(body["events"][0])


def test_outbox_endpoint_after_send(tmp_path: Path) -> None:
    client, _ = _app(outbox_dir=tmp_path)
    sid = _new(client)
    assert client.get(f"/api/sessions/{sid}/outbox").json() == []
    _say(client, sid, MARGARET_OPENER)
    assert _say(client, sid, "That's all, thanks.").json()["state"]["phase"] == "POST_PROCESS"
    _press(client, sid, "email_send")
    assert _press(client, sid, "email_confirm").json()["state"]["phase"] == "CLOSED"
    items = client.get(f"/api/sessions/{sid}/outbox").json()
    assert len(items) == 1
    assert items[0]["to"] == "margaret@email.com" and "CL-2048" in items[0]["body"]
    assert len(list(tmp_path.glob(f"{sid}-MSG-*.eml"))) == 1


def test_session_store_ttl_cleanup() -> None:
    store = SessionStore(ttl_min=1)
    old = store.create("default")
    store._touched[old.session_id] -= 61  # age it past the TTL
    store.create("default")
    assert store.get(old.session_id) is None


# --- events / concurrency -----------------------------------------------------------


def test_events_poll_never_calls_llm() -> None:
    client, rec = _app()
    sid = _new(client, "timeout")
    _say(client, sid, DAVID_TEXT)
    calls = len(rec.cfgs)
    r = client.post(f"/api/sessions/{sid}/events", json={"type": "consent_poll"})
    assert r.status_code == 200
    assert r.json()["state"]["consent"]["polls"] == 1
    assert len(rec.cfgs) == calls
    bad = client.post(f"/api/sessions/{sid}/events", json={"type": "other"})
    assert bad.status_code == 422


def test_events_do_not_consume_quota() -> None:
    client, _ = _app()
    client.app.state.limiter = SlidingWindowLimiter(1, 300, 3000)  # type: ignore[attr-defined]
    sid = _new(client, "timeout")
    _new(client)  # session creation is free too
    assert _say(client, sid, DAVID_TEXT).status_code == 200
    for _ in range(3):
        r = client.post(f"/api/sessions/{sid}/events", json={"type": "consent_poll"})
        assert r.status_code == 200


class SlowResponder:
    """Template responder that sleeps and records how many turns overlap."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._lock:
            self.active -= 1
        return render(rctx.directives, rctx)


def test_s17_concurrent_message_and_poll_serialized() -> None:
    slow = SlowResponder()
    client, rec = _app(Recorder(responder=slow))
    app = client.app
    sid = _new(client, "timeout")
    assert _say(client, sid, DAVID_TEXT).json()["state"]["sub_state"] == "CONSENT_PENDING"
    slow.max_active = 0
    # The poll turn must hit the same slow path to prove serialization.
    app.state.event_bundle = lambda: rec(  # type: ignore[attr-defined]
        ProviderConfig("openai", None, "fake")
    )

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return list(
                await asyncio.gather(
                    ac.post(f"/api/sessions/{sid}/messages", json={"text": "Any news yet?"}),
                    ac.post(f"/api/sessions/{sid}/events", json={"type": "consent_poll"}),
                    ac.post(f"/api/sessions/{sid}/messages", json={"text": "Still waiting."}),
                )
            )

    responses = asyncio.run(run())
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert slow.max_active == 1
    state = client.get(f"/api/sessions/{sid}/state").json()
    assert state["consent"]["polls"] == 3
    assert state["counters"]["turns"] == 4
    transcript = client.get(f"/api/sessions/{sid}/transcript").json()["transcript"]
    assert [m["turn"] for m in transcript if m["role"] == "agent"] == [0, 1, 2, 3, 4]


# --- keys, providers, rate limits ---------------------------------------------------


def test_missing_key_401() -> None:
    client, rec = _app(openai_api_key=None)
    sid = _new(client)
    r = _say(client, sid, "hello")
    assert r.status_code == 401
    assert r.json() == {"code": "missing_api_key"}
    assert rec.cfgs == []
    assert client.get(f"/api/sessions/{sid}/state").json()["counters"]["turns"] == 0


def test_invalid_provider_header_400() -> None:
    client, _ = _app()
    sid = _new(client)
    r = _say(client, sid, "hello", **{"X-OpenAI-Key": USER_KEY, "X-LLM-Provider": "acme"})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_provider" and r.json()["detail"]
    assert USER_KEY not in r.text
    r = _say(
        client,
        sid,
        "hello",
        **{
            "X-OpenAI-Key": USER_KEY,
            "X-LLM-Provider": "custom",
            "X-LLM-Base-URL": "https://10.0.0.1/v1",
            "X-LLM-Model": "m",
        },
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_provider"


def test_client_key_header_used() -> None:
    client, rec = _app()
    sid = _new(client)
    r = _say(
        client,
        sid,
        "hello",
        **{"X-OpenAI-Key": USER_KEY, "X-LLM-Provider": "deepseek", "X-LLM-Model": "deepseek-x"},
    )
    assert r.status_code == 200
    cfg = rec.cfgs[-1]
    assert cfg.api_key == USER_KEY and not cfg.uses_server_key
    assert (cfg.name, cfg.model) == ("deepseek", "deepseek-x")
    assert USER_KEY not in r.text and SERVER_KEY not in r.text


def test_s24_server_key_rate_limited() -> None:
    client, _ = _app()
    client.app.state.limiter = SlidingWindowLimiter(2, 300, 3000)  # type: ignore[attr-defined]
    sid = _new(client)
    assert _say(client, sid, "hello").status_code == 200
    assert _say(client, sid, "hello").status_code == 200
    r = _say(client, sid, "hello")
    assert r.status_code == 429
    assert r.json() == {"code": "demo_quota_exceeded"}
    # A rejected request never reaches the engine.
    assert client.get(f"/api/sessions/{sid}/state").json()["counters"]["turns"] == 2
    # Bring-your-own-key requests are not limited.
    for _ in range(3):
        assert _say(client, sid, "hello", **{"X-OpenAI-Key": USER_KEY}).status_code == 200


def test_s24_client_model_ignored_with_server_key() -> None:
    client, rec = _app(openai_model="gpt-5-mini")
    sid = _new(client)
    r = _say(
        client,
        sid,
        "hello",
        **{
            "X-LLM-Provider": "custom",
            "X-LLM-Base-URL": "https://expensive.example.com/v1",
            "X-LLM-Model": "gpt-4.5-preview",
        },
    )
    assert r.status_code == 200
    cfg = rec.cfgs[-1]
    assert cfg.uses_server_key and cfg.api_key == SERVER_KEY
    assert (cfg.name, cfg.base_url, cfg.model) == ("openai", None, "gpt-5-mini")
    assert SERVER_KEY not in r.text


def _limited_app(**kw: Any) -> tuple[TestClient, str]:
    client, _ = _app(**kw)
    client.app.state.limiter = SlidingWindowLimiter(1, 300, 3000)  # type: ignore[attr-defined]
    return client, _new(client)


def test_trusted_proxy_keys_on_rightmost_forwarded_entry() -> None:
    client, sid = _limited_app(trust_proxy=True)
    # Spoofed leftmost values rotate; the proxy-appended rightmost value is the real client.
    h1 = {"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}
    h2 = {"X-Forwarded-For": "2.2.2.2 ,  203.0.113.9 "}
    assert _say(client, sid, "hello", **h1).status_code == 200
    assert _say(client, sid, "hello", **h2).status_code == 429
    # A different real client (rightmost) has its own bucket.
    h3 = {"X-Forwarded-For": "1.1.1.1, 198.51.100.7"}
    assert _say(client, sid, "hello", **h3).status_code == 200


def test_trusted_proxy_falls_back_to_peer_without_header() -> None:
    client, sid = _limited_app(trust_proxy=True)
    assert _say(client, sid, "hello", **{"X-Forwarded-For": " , "}).status_code == 200
    assert _say(client, sid, "hello").status_code == 429  # same peer (testclient)


def test_untrusted_proxy_ignores_forwarded_header() -> None:
    client, sid = _limited_app(trust_proxy=False)
    assert _say(client, sid, "hello", **{"X-Forwarded-For": "203.0.113.1"}).status_code == 200
    assert _say(client, sid, "hello", **{"X-Forwarded-For": "203.0.113.2"}).status_code == 429


def test_empty_key_header_counts_as_server_key() -> None:
    client, sid = _limited_app()
    assert _say(client, sid, "hello", **{"X-OpenAI-Key": ""}).status_code == 200
    r = _say(client, sid, "hello", **{"X-OpenAI-Key": ""})
    assert r.status_code == 429 and r.json() == {"code": "demo_quota_exceeded"}


def test_state_and_transcript_wait_for_running_turn() -> None:
    slow = SlowResponder()
    client, _ = _app(Recorder(responder=slow))
    app = client.app
    sid = _new(client)

    async def run() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            turn = asyncio.create_task(
                ac.post(f"/api/sessions/{sid}/messages", json={"text": "hello"})
            )
            await asyncio.sleep(0.01)  # the turn holds the lock and sleeps in the responder
            state, transcript = await asyncio.gather(
                ac.get(f"/api/sessions/{sid}/state"), ac.get(f"/api/sessions/{sid}/transcript")
            )
            await turn
            return state.json()["counters"]["turns"], len(transcript.json()["transcript"])

    turns, messages = asyncio.run(run())
    assert (turns, messages) == (1, 3)  # read after the turn completed, never mid-turn


def test_sliding_window_limiter() -> None:
    lim = SlidingWindowLimiter(per_ip_per_min=2, per_ip_per_day=3, global_per_day=4)
    assert lim.check("a", 0.0) and lim.check("a", 1.0)
    assert not lim.check("a", 2.0)  # per-minute
    assert lim.check("a", 61.0)
    assert not lim.check("a", 200.0)  # per-day (3 used)
    assert lim.check("b", 200.0)
    assert not lim.check("c", 201.0)  # global (4 used)
    assert lim.check("a", 86_401.0)  # first day's entries have expired


# --- validate-key -------------------------------------------------------------------


class FakeClient:
    def __init__(self, cfg: ProviderConfig, fail: LLMError | None, seen: list[Any]) -> None:
        self.fail = fail
        seen.append(cfg)
        self.seen = seen

    def chat(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        self.seen.append(kw)
        if self.fail is not None:
            raise self.fail
        return {"content": ""}


def _validator_app(fail: LLMError | None = None) -> tuple[TestClient, list[Any]]:
    client, _ = _app()
    seen: list[Any] = []
    client.app.state.llm_client_factory = (  # type: ignore[attr-defined]
        lambda cfg: FakeClient(cfg, fail, seen)
    )
    return client, seen


def test_validate_key_ok_uses_request_values() -> None:
    client, seen = _validator_app()
    r = client.post(
        "/api/config/validate-key",
        json={"provider": "deepseek", "model": "deepseek-chat", "api_key": USER_KEY},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    cfg, kw = seen
    assert cfg.api_key == USER_KEY and not cfg.uses_server_key and cfg.name == "deepseek"
    assert kw == {"max_tokens": 1}


def test_validate_key_reports_error_kind() -> None:
    client, _ = _validator_app(LLMError("auth", "Authentication failed"))
    r = client.post("/api/config/validate-key", json={"provider": "openai", "api_key": USER_KEY})
    assert r.json() == {"ok": False, "error": "auth"}
    assert USER_KEY not in r.text


def test_s19_validate_key_rejects_private_url() -> None:
    client, seen = _validator_app()
    for url in ("https://127.0.0.1/v1", "https://169.254.169.254/", "http://api.example.com"):
        r = client.post(
            "/api/config/validate-key",
            json={"provider": "custom", "base_url": url, "model": "m", "api_key": USER_KEY},
        )
        assert r.status_code == 400, url
        assert r.json()["code"] == "invalid_provider"
    assert seen == []


def test_validate_key_never_uses_server_key_and_never_echoes_input() -> None:
    client, seen = _validator_app()
    r = client.post("/api/config/validate-key", json={"provider": "openai", "api_key": ""})
    assert r.status_code == 422
    r = client.post("/api/config/validate-key", json={"provider": 7, "api_key": USER_KEY})
    assert r.status_code == 422
    assert USER_KEY not in r.text
    assert seen == []


# --- logging and errors -------------------------------------------------------------


def test_log_redacts_keys(caplog: pytest.LogCaptureFixture) -> None:
    create_app(_settings())
    log = logging.getLogger("app.somewhere")
    with caplog.at_level(logging.INFO):
        log.info("using key %s", USER_KEY)
        log.warning("inline sk-abcdefgh12345678 and short sk-abc")
        logging.getLogger().error("root %(k)s", {"k": SERVER_KEY})
        try:
            raise RuntimeError(f"bad {USER_KEY}")
        except RuntimeError:
            log.exception("failed")
    text = caplog.text
    assert USER_KEY not in text and SERVER_KEY not in text
    assert "sk-abcdefgh12345678" not in text
    assert "sk-***" in text and "short sk-abc" in text
    assert all("sk-user" not in r.getMessage() for r in caplog.records)


def test_unexpected_exception_returns_500_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _app()

    def boom(cfg: ProviderConfig) -> LLMBundle:
        raise RuntimeError(f"kaboom {cfg.api_key}")

    client.app.state.llm_factory = boom  # type: ignore[attr-defined]
    sid = _new(client)
    with caplog.at_level(logging.ERROR):
        r = _say(client, sid, "hello")
    assert r.status_code == 500
    assert r.json() == {"code": "internal_error"}
    assert "Traceback" not in r.text and "kaboom" not in r.text
    assert "kaboom" in caplog.text and SERVER_KEY not in caplog.text
    # The session lock was released: the session still works.
    client.app.state.llm_factory = Recorder()  # type: ignore[attr-defined]
    assert _say(client, sid, "hello").status_code == 200


# --- static frontend and CORS -------------------------------------------------------


def test_static_frontend_mounted_when_present(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>demo</html>", encoding="utf-8")
    client, _ = _app(frontend_dir=tmp_path)
    assert "demo" in client.get("/").text
    assert client.get("/api/health").json() == {"status": "ok"}
    no_dist, _ = _app()
    assert no_dist.get("/").status_code == 404


def test_cors_allows_dev_origin_only() -> None:
    client, _ = _app()
    headers = {"Access-Control-Request-Method": "POST"}
    ok = client.options("/api/sessions", headers={"Origin": "http://localhost:5173", **headers})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/sessions", headers={"Origin": "https://evil.example", **headers})
    assert "access-control-allow-origin" not in bad.headers
