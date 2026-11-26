import json
import socket
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.llm import client as client_mod
from app.llm.base import LLMError
from app.llm.client import (
    InvalidProviderConfig,
    LLMClient,
    LLMHeaders,
    MissingApiKey,
    ProviderConfig,
    resolve_provider,
    validate_base_url,
)
from app.settings import Settings

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod.socket, "getaddrinfo", lambda *a, **k: PUBLIC)


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_header_key_overrides_server() -> None:
    s = _settings(openai_api_key="srv", openai_model="gpt-4.1-mini")
    cfg = resolve_provider(LLMHeaders(api_key="mine", provider="deepseek"), s)
    assert cfg.api_key == "mine"
    assert cfg.name == "deepseek"
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.model == "deepseek-chat"
    assert (cfg.supports_structured, cfg.supports_tools) == (False, True)
    assert cfg.uses_server_key is False


def test_header_key_defaults_to_openai() -> None:
    cfg = resolve_provider(LLMHeaders(api_key="k"), _settings())
    assert (cfg.name, cfg.base_url, cfg.model) == ("openai", None, "gpt-4.1-mini")
    assert (cfg.supports_structured, cfg.supports_tools) == (True, True)


def test_default_openai_model_is_gpt_4_1_mini() -> None:
    assert resolve_provider(LLMHeaders(api_key="k"), _settings()).model == "gpt-4.1-mini"
    srv = resolve_provider(LLMHeaders(), _settings(openai_api_key="srv"))
    assert srv.model == "gpt-4.1-mini" and srv.uses_server_key


def test_server_key_ignores_client_model() -> None:
    s = _settings(openai_api_key="srv", openai_model="gpt-4.1-mini")
    h = LLMHeaders(provider="custom", base_url="https://evil.example.com", model="gpt-4o")
    cfg = resolve_provider(h, s)
    assert cfg.uses_server_key is True
    assert cfg.api_key == "srv"
    assert cfg.model == "gpt-4.1-mini"
    assert cfg.name == "openai"
    assert cfg.base_url is None


def test_server_key_custom_provider_validates_base_url() -> None:
    s = _settings(
        openai_api_key="srv",
        llm_provider="custom",
        openai_base_url="https://llm.example.com/v1/",
        openai_model="m",
    )
    cfg = resolve_provider(LLMHeaders(), s)
    assert cfg.base_url == "https://llm.example.com/v1"
    assert (cfg.supports_structured, cfg.supports_tools) == (False, False)
    bad = _settings(
        openai_api_key="srv",
        llm_provider="custom",
        openai_base_url="http://x.com",
        openai_model="m",
    )
    with pytest.raises(InvalidProviderConfig):
        resolve_provider(LLMHeaders(), bad)


def test_missing_key_raises() -> None:
    with pytest.raises(MissingApiKey):
        resolve_provider(LLMHeaders(model="x"), _settings())


@pytest.mark.parametrize(
    "h",
    [
        LLMHeaders(api_key="k", provider="custom", model="m"),
        LLMHeaders(api_key="k", provider="custom", base_url="https://api.x.com"),
        LLMHeaders(api_key="k", provider="bogus"),
        LLMHeaders(api_key="k", provider="custom", base_url="http://api.x.com", model="m"),
    ],
)
def test_custom_requires_base_url_and_model(h: LLMHeaders) -> None:
    with pytest.raises(InvalidProviderConfig):
        resolve_provider(h, _settings())


def test_custom_valid() -> None:
    h = LLMHeaders(api_key="k", provider="custom", base_url="https://api.x.com/v1/", model="m")
    cfg = resolve_provider(h, _settings())
    assert cfg.base_url == "https://api.x.com/v1"
    assert cfg.model == "m"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.x.com",
        "https://localhost",
        "https://foo.localhost",
        "https://10.0.0.1",
        "https://169.254.1.1",
        "https://127.0.0.1",
        "https://[::1]",
        "https://0.0.0.0",
        "https:///nohost",
        "https://a.com:99999",
        "https://100.64.0.1",
        "https://[fec0::1]",
        "https://u:p@api.example.com",
    ],
)
def test_validate_base_url_rejects(url: str) -> None:
    with pytest.raises(InvalidProviderConfig):
        validate_base_url(url)


def test_validate_base_url_rejects_domain_resolving_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(client_mod.socket, "getaddrinfo", lambda *a, **k: PUBLIC + loop)
    with pytest.raises(InvalidProviderConfig):
        validate_base_url("https://sneaky.example.com")


def test_validate_base_url_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise socket.gaierror("nope")

    monkeypatch.setattr(client_mod.socket, "getaddrinfo", boom)
    with pytest.raises(InvalidProviderConfig):
        validate_base_url("https://nx.example.com")


def test_validate_base_url_accepts_public() -> None:
    assert validate_base_url("https://api.deepseek.com/") == "https://api.deepseek.com"


# --- client ---


def _cfg(model: str = "gpt-4.1-mini", structured: bool = True) -> ProviderConfig:
    return ProviderConfig(
        name="openai",
        base_url=None,
        model=model,
        api_key="sk-secret",
        supports_structured=structured,
        supports_tools=True,
        uses_server_key=False,
    )


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


def _make(
    handler: Any, cfg: ProviderConfig | None = None
) -> tuple[LLMClient, list[httpx.Request], list[float]]:
    reqs: list[httpx.Request] = []
    sleeps: list[float] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        reqs.append(req)
        return handler(req, len(reqs))  # type: ignore[no-any-return]

    c = LLMClient(
        cfg or _cfg(),
        http_client=httpx.Client(transport=httpx.MockTransport(wrapped)),
        sleep=sleeps.append,
    )
    return c, reqs, sleeps


def test_chat_returns_message() -> None:
    c, _, _ = _make(lambda r, n: httpx.Response(200, json=_completion("hi")))
    assert c.chat([{"role": "user", "content": "x"}]).content == "hi"


def test_retry_on_429_then_rate_limit_error() -> None:
    c, reqs, sleeps = _make(lambda r, n: httpx.Response(429, json={"error": {"message": "slow"}}))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "rate_limit"
    assert len(reqs) == 3
    assert sleeps == [0.5, 1.0]


def test_retry_then_success() -> None:
    def h(r: httpx.Request, n: int) -> httpx.Response:
        if n < 2:
            return httpx.Response(503, json={"error": {"message": "down"}})
        return httpx.Response(200, json=_completion("ok"))

    c, reqs, _ = _make(h)
    assert c.chat([{"role": "user", "content": "x"}]).content == "ok"
    assert len(reqs) == 2


def test_5xx_exhausted_is_other() -> None:
    c, reqs, _ = _make(lambda r, n: httpx.Response(500, json={"error": {"message": "x"}}))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "other"
    assert len(reqs) == 3


@pytest.mark.parametrize("status", [401, 403])
def test_auth_no_retry(status: int) -> None:
    c, reqs, _ = _make(lambda r, n: httpx.Response(status, json={"error": {"message": "bad"}}))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "auth"
    assert len(reqs) == 1
    assert "sk-secret" not in str(ei.value)


def test_timeout_no_retry() -> None:
    def h(r: httpx.Request, n: int) -> httpx.Response:
        raise httpx.ReadTimeout("t", request=r)

    c, reqs, _ = _make(h)
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "timeout"
    assert len(reqs) == 1


def test_connection_error_is_other() -> None:
    def h(r: httpx.Request, n: int) -> httpx.Response:
        raise httpx.ConnectError("c", request=r)

    c, _, _ = _make(h)
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "other"


def test_gpt5_no_temperature() -> None:
    c, reqs, _ = _make(lambda r, n: httpx.Response(200, json=_completion("hi")), _cfg("gpt-5-mini"))
    c.chat([{"role": "user", "content": "x"}], max_tokens=5)
    body = json.loads(reqs[0].content)
    assert "temperature" not in body
    assert body["reasoning_effort"] == "minimal"
    assert body["max_completion_tokens"] == 5
    assert "max_tokens" not in body


def test_non_gpt5_temperature_and_max_tokens() -> None:
    c, reqs, _ = _make(
        lambda r, n: httpx.Response(200, json=_completion("hi")), _cfg("deepseek-chat", False)
    )
    c.chat([{"role": "user", "content": "x"}], max_tokens=5, json_mode=True)
    body = json.loads(reqs[0].content)
    assert body["temperature"] == 0.3
    assert "reasoning_effort" not in body
    assert body["max_tokens"] == 5
    assert body["response_format"] == {"type": "json_object"}


class Out(BaseModel):
    a: int


def test_parse_structured() -> None:
    c, reqs, _ = _make(lambda r, n: httpx.Response(200, json=_completion('{"a": 3}')))
    assert c.parse([{"role": "user", "content": "x"}], Out) == Out(a=3)
    assert json.loads(reqs[0].content)["response_format"]["type"] == "json_schema"


def test_parse_json_mode_retries_once_then_other() -> None:
    c, reqs, _ = _make(
        lambda r, n: httpx.Response(200, json=_completion("not json")), _cfg("deepseek-chat", False)
    )
    with pytest.raises(LLMError) as ei:
        c.parse([{"role": "user", "content": "x"}], Out)
    assert ei.value.kind == "other"
    assert len(reqs) == 2
    assert json.loads(reqs[0].content)["temperature"] == 0


def test_parse_json_mode_recovers_on_retry() -> None:
    def h(r: httpx.Request, n: int) -> httpx.Response:
        return httpx.Response(200, json=_completion("oops" if n == 1 else '{"a": 1}'))

    c, reqs, _ = _make(h, _cfg("deepseek-chat", False))
    assert c.parse([{"role": "user", "content": "x"}], Out) == Out(a=1)
    assert len(reqs) == 2


def test_validate_rejects_v4_mapped_and_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    mapped = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 443, 0, 0))]
    monkeypatch.setattr(client_mod.socket, "getaddrinfo", lambda *a, **k: mapped)
    with pytest.raises(InvalidProviderConfig):
        validate_base_url("https://mapped.example.com")
    loop = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(client_mod.socket, "getaddrinfo", lambda *a, **k: loop)
    with pytest.raises(InvalidProviderConfig):
        validate_base_url("https://2130706433")


def test_api_key_not_in_repr() -> None:
    assert "sk-secret" not in repr(_cfg())
    assert "sk-secret" not in repr(LLMHeaders(api_key="sk-secret"))


def test_redirect_not_followed_and_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(307, headers={"location": "http://169.254.169.254/x"})

    real = httpx.Client
    # Exercise the default-client path (follow_redirects=False) over a mock transport.
    monkeypatch.setattr(
        client_mod.openai,
        "DefaultHttpxClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    c = LLMClient(_cfg(), sleep=lambda s: None)
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "other"
    assert len(seen) == 1


def test_structured_parse_sdk_errors_wrapped() -> None:
    c, _, _ = _make(lambda r, n: httpx.Response(200, json=_completion("not json")))
    with pytest.raises(LLMError) as ei:
        c.parse([{"role": "user", "content": "x"}], Out)
    assert ei.value.kind == "other"


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"message": message, "type": "invalid_request_error", **extra}}


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, _err("The model `gpt-4.1-mini` does not exist", code="model_not_found")),
        (400, _err("Your organization must be verified to use the model `gpt-4.1-mini`.")),
        (400, _err("Unsupported value", param="model")),
        (403, _err("Project does not have access to model `gpt-4.1-mini`")),
    ],
)
def test_model_errors_are_model_unavailable(status: int, body: dict[str, Any]) -> None:
    c, reqs, _ = _make(lambda r, n: httpx.Response(status, json=body))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "model_unavailable"
    assert len(reqs) == 1


def test_other_bad_request_stays_other() -> None:
    body = _err("This model's maximum context length is 128000 tokens.", param="messages")
    c, _, _ = _make(lambda r, n: httpx.Response(400, json=body))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "other"


def test_blank_base_url_env_does_not_leak_into_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    c, reqs, _ = _make(lambda r, n: httpx.Response(200, json=_completion("hi")))
    c.chat([{"role": "user", "content": "x"}])
    assert str(reqs[0].url) == "https://api.openai.com/v1/chat/completions"


def test_blank_env_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "DEMO_TODAY", "OUTBOX_DIR"):
        monkeypatch.setenv(k, " ")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.openai_api_key is None and s.openai_base_url is None
    assert s.openai_model is None and s.demo_today is None and s.outbox_dir is None
    with pytest.raises(MissingApiKey):
        resolve_provider(LLMHeaders(), s)
    cfg = resolve_provider(LLMHeaders(api_key="k"), s)
    assert cfg.model == "gpt-4.1-mini"
    monkeypatch.setenv("OPENAI_API_KEY", "srv")
    cfg = resolve_provider(LLMHeaders(), Settings(_env_file=None))  # type: ignore[call-arg]
    assert cfg.model == "gpt-4.1-mini" and cfg.uses_server_key


def test_short_custom_model_name_does_not_misclassify() -> None:
    body = _err("Invalid 'messages': model input was malformed.", param="messages")
    c, _, _ = _make(lambda r, n: httpx.Response(400, json=body), cfg=_cfg(model="m"))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "other"


def test_short_custom_model_name_still_matches_as_token() -> None:
    body = _err("The model `m` is not available on this server.")
    c, _, _ = _make(lambda r, n: httpx.Response(400, json=body), cfg=_cfg(model="m"))
    with pytest.raises(LLMError) as ei:
        c.chat([{"role": "user", "content": "x"}])
    assert ei.value.kind == "model_unavailable"
