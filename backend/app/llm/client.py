"""Provider-neutral LLM client: provider resolution, SSRF guard, retries, error classification.

Server-key safety: when the caller supplies no key of their own, every client-supplied
provider/base URL/model is ignored, so the capped server key can only ever reach the
server-configured endpoint and model.
"""

import ipaddress
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.llm.base import LLMError
from app.settings import Settings

T = TypeVar("T", bound=BaseModel)
ProviderName = Literal["openai", "deepseek", "custom"]

_DEEPSEEK_URL = "https://api.deepseek.com"
_OPENAI_URL = "https://api.openai.com/v1"
_DEFAULT_MODELS: dict[str, str] = {"openai": "gpt-4.1-mini", "deepseek": "deepseek-chat"}
# name -> (supports_structured, supports_tools)
_CAPABILITIES: dict[str, tuple[bool, bool]] = {
    "openai": (True, True),
    "deepseek": (False, True),
    "custom": (False, False),
}
_RETRY_SLEEPS = (0.5, 1.0)


@dataclass(frozen=True)
class LLMHeaders:
    api_key: str | None = field(default=None, repr=False)
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ProviderConfig:
    name: ProviderName
    base_url: str | None
    model: str
    api_key: str = field(default="", repr=False)
    supports_structured: bool = False
    supports_tools: bool = False
    uses_server_key: bool = False


class MissingApiKey(Exception):
    pass


class InvalidProviderConfig(Exception):
    pass


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        not ip.is_global
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_base_url(url: str) -> str:
    """Reject anything that could point the client at an internal address (SSRF)."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 443
        userinfo = parsed.username is not None or parsed.password is not None
    except ValueError as e:
        raise InvalidProviderConfig("Invalid base URL") from e
    if parsed.scheme != "https":
        raise InvalidProviderConfig("Base URL must use https")
    if not host:
        raise InvalidProviderConfig("Base URL must include a hostname")
    if userinfo:
        raise InvalidProviderConfig("Base URL must not contain credentials")
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise InvalidProviderConfig("Base URL host is not allowed")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise InvalidProviderConfig("Base URL host is not allowed")
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            raise InvalidProviderConfig("Base URL host could not be resolved") from e
        if not infos:
            raise InvalidProviderConfig("Base URL host could not be resolved")
        for info in infos:
            addr = str(info[4][0]).split("%")[0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError as e:
                raise InvalidProviderConfig("Base URL resolved to an invalid address") from e
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            if _blocked_ip(ip):
                raise InvalidProviderConfig("Base URL host is not allowed")
    return url.rstrip("/")


def _build(
    name: str, base_url: str | None, model: str, api_key: str, uses_server_key: bool
) -> ProviderConfig:
    if name not in _CAPABILITIES:
        raise InvalidProviderConfig(f"Unknown provider: {name}")
    structured, tools = _CAPABILITIES[name]
    provider: ProviderName = name  # type: ignore[assignment]
    return ProviderConfig(provider, base_url, model, api_key, structured, tools, uses_server_key)


def resolve_provider(h: LLMHeaders, s: Settings) -> ProviderConfig:
    if h.api_key:
        name = h.provider or "openai"
        if name == "custom":
            if not h.base_url or not h.model:
                raise InvalidProviderConfig("Custom provider requires a base URL and a model")
            return _build(name, validate_base_url(h.base_url), h.model, h.api_key, False)
        if name == "openai":
            return _build(name, None, h.model or _DEFAULT_MODELS["openai"], h.api_key, False)
        if name == "deepseek":
            return _build(
                name, _DEEPSEEK_URL, h.model or _DEFAULT_MODELS["deepseek"], h.api_key, False
            )
        raise InvalidProviderConfig(f"Unknown provider: {name}")
    if not s.openai_api_key:
        raise MissingApiKey("No API key supplied")
    name = s.llm_provider
    if name == "custom":
        if not s.openai_base_url or not s.openai_model:
            raise InvalidProviderConfig("Server custom provider requires a base URL and a model")
        return _build(
            name, validate_base_url(s.openai_base_url), s.openai_model, s.openai_api_key, True
        )
    default_url = _DEEPSEEK_URL if name == "deepseek" else None
    return _build(
        name,
        s.openai_base_url or default_url,
        s.openai_model or _DEFAULT_MODELS[name],
        s.openai_api_key,
        True,
    )


class LLMClient:
    def __init__(
        self,
        cfg: ProviderConfig,
        timeout_s: float = 20.0,
        *,
        http_client: Any = None,  # openai 3.x types this as httpx2.Client; tests inject httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = cfg
        self._sleep = sleep
        # SDK retries are disabled: retry/backoff policy lives in _call. Redirects are never
        # followed (the SDK default is to follow), or a validated host could bounce us inward.
        if http_client is None:
            http_client = openai.DefaultHttpxClient(follow_redirects=False)
        self._client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url
            or _OPENAI_URL,  # explicit: never let the SDK read OPENAI_BASE_URL
            http_client=http_client,
            timeout=timeout_s,
            max_retries=0,
        )

    @property
    def config(self) -> ProviderConfig:
        return self._cfg

    @property
    def _is_gpt5(self) -> bool:
        return self._cfg.model.startswith("gpt-5")

    def _kwargs(
        self, messages: list[dict[str, Any]], temperature: float, max_tokens: int | None
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {"model": self._cfg.model, "messages": messages}
        if self._is_gpt5:
            kw["reasoning_effort"] = "minimal"
            if max_tokens is not None:
                kw["max_completion_tokens"] = max_tokens
        else:
            kw["temperature"] = temperature
            if max_tokens is not None:
                kw["max_tokens"] = max_tokens
        return kw

    def _is_model_error(self, e: openai.APIStatusError) -> bool:
        """True when the provider rejected the request because of the chosen model."""
        if isinstance(e, openai.NotFoundError):
            return True
        body = e.body if isinstance(e.body, dict) else {}
        if body.get("param") == "model" or body.get("code") == "model_not_found":
            return True
        model, message = self._cfg.model, str(e.message)
        if not model or "model" not in message.lower():
            return False
        # Whole-token match, so a short custom model name ("m", "gpt") cannot hit inside a word.
        return re.search(rf"(?<![\w.:/-]){re.escape(model)}(?![\w.:/-])", message) is not None

    def _call(self, fn: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            try:
                return fn()
            except openai.AuthenticationError as e:
                raise LLMError("auth", "Authentication failed") from e
            except openai.PermissionDeniedError as e:
                if self._is_model_error(e):
                    raise LLMError("model_unavailable", "Model not available for this key") from e
                raise LLMError("auth", "Authentication failed") from e
            except openai.APITimeoutError as e:
                raise LLMError("timeout", "Request timed out") from e
            except openai.APIConnectionError as e:
                raise LLMError("other", "Connection error") from e
            except openai.APIStatusError as e:
                rate = isinstance(e, openai.RateLimitError)
                if e.status_code in (400, 404) and self._is_model_error(e):
                    raise LLMError("model_unavailable", "Model not available for this key") from e
                if not (rate or e.status_code >= 500):
                    raise LLMError("other", f"Provider returned HTTP {e.status_code}") from e
                if attempt >= len(_RETRY_SLEEPS):
                    kind: Literal["rate_limit", "other"] = "rate_limit" if rate else "other"
                    raise LLMError(kind, f"Provider returned HTTP {e.status_code}") from e
                self._sleep(_RETRY_SLEEPS[attempt])
                attempt += 1

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> Any:
        kw = self._kwargs(messages, 0.3, max_tokens)
        if tools:
            kw["tools"] = tools
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        resp = self._call(lambda: self._client.chat.completions.create(**kw))
        return resp.choices[0].message

    def parse(self, messages: list[dict[str, Any]], schema: type[T]) -> T:
        if self._cfg.supports_structured:
            kw = self._kwargs(messages, 0, None)
            try:
                resp = self._call(
                    lambda: self._client.chat.completions.parse(response_format=schema, **kw)
                )
            except LLMError:
                raise
            except (openai.OpenAIError, ValidationError) as e:
                raise LLMError("other", "Structured output could not be parsed") from e
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMError("other", "Structured output could not be parsed")
            return parsed  # type: ignore[no-any-return]
        kw = self._kwargs(messages, 0, None)
        kw["response_format"] = {"type": "json_object"}
        for attempt in range(2):
            resp = self._call(lambda: self._client.chat.completions.create(**kw))
            try:
                return schema.model_validate_json(resp.choices[0].message.content or "")
            except ValidationError:
                if attempt == 1:
                    raise LLMError("other", "Model output failed schema validation") from None
        raise LLMError("other", "Model output failed schema validation")  # pragma: no cover
