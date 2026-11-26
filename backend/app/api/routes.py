"""REST routes (spec §12) and the API's error handling.

Per request: async route -> session lock -> ``await run_in_threadpool(engine...)``, so a
session's user messages and consent polls are applied strictly one at a time.

Server-key safety: provider resolution ignores client provider/base URL/model unless the
client brings its own key; server-key turns are rate limited per IP *before* the engine
runs; no key ever appears in a response. Consent polls are system events: they use a
template-only bundle, so they never call the LLM and never consume quota.
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.ratelimit import SlidingWindowLimiter
from app.api.schemas import (
    CONSENT_SCENARIOS,
    ConfigOut,
    EventIn,
    MessageIn,
    MessageOut,
    QuickReplyOut,
    SessionIn,
    SessionOut,
    TurnOut,
    ValidateKeyIn,
    ValidateKeyOut,
)
from app.api.sessions import SessionStore
from app.llm.base import ExtractContext, LLMBundle, LLMError
from app.llm.client import (
    InvalidProviderConfig,
    LLMHeaders,
    MissingApiKey,
    ProviderConfig,
    resolve_provider,
)
from app.settings import Settings, today
from app.sop.context import ResponderContext
from app.sop.email_summary import EmailDraft
from app.sop.engine import Engine, TurnResult
from app.sop.extraction import Extraction
from app.sop.snapshot import public_snapshot
from app.sop.state import SessionState
from app.sop.templates import render

logger = logging.getLogger("app.api")
router = APIRouter(prefix="/api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail


# --- template-only bundle for consent polls ----------------------------------------


class _NoExtractor:
    def extract(self, text: str, ectx: ExtractContext) -> Extraction:
        raise LLMError("other", "events carry no user text")  # pragma: no cover


class _TemplateResponder:
    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str:
        return render(rctx.directives, rctx)


class _PassThroughComposer:
    def compose(self, state: SessionState, draft: EmailDraft) -> EmailDraft:
        return draft  # pragma: no cover - events never send email


def template_bundle() -> LLMBundle:
    """A bundle that never calls an LLM: deterministic templates only."""
    return LLMBundle(
        extractor=_NoExtractor(),
        responder=_TemplateResponder(),
        email_composer=_PassThroughComposer(),
    )


# --- helpers ------------------------------------------------------------------------


def _session(request: Request, session_id: str) -> SessionState:
    store: SessionStore = request.app.state.sessions
    state = store.get(session_id)
    if state is None:
        raise ApiError(404, "session_not_found")
    return state


def _headers(request: Request) -> LLMHeaders:
    h = request.headers
    return LLMHeaders(
        api_key=h.get("x-openai-key") or None,
        provider=h.get("x-llm-provider") or None,
        base_url=h.get("x-llm-base-url") or None,
        model=h.get("x-llm-model") or None,
    )


async def _resolve(headers: LLMHeaders, settings: Settings) -> ProviderConfig:
    # Off the event loop: a custom base URL is DNS-resolved for the SSRF check.
    try:
        return await run_in_threadpool(resolve_provider, headers, settings)
    except MissingApiKey:
        raise ApiError(401, "missing_api_key") from None
    except InvalidProviderConfig as e:
        raise ApiError(400, "invalid_provider", str(e)) from None


def _client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    if settings.trust_proxy:
        # The proxy appends the real peer on the right; anything left of it is client-supplied.
        entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",")]
        entries = [e for e in entries if e]
        if entries:
            return entries[-1]
    return request.client.host if request.client is not None else "unknown"


def _turn_out(result: TurnResult) -> TurnOut:
    return TurnOut(
        messages=[MessageOut(role=m.role, text=m.text) for m in result.messages],
        state=result.snapshot,
        quick_replies=[QuickReplyOut(label=q.label, action=q.action) for q in result.quick_replies],
        llm_error=result.llm_error,
    )


async def _run_turn(request: Request, session_id: str, llm: LLMBundle, **kw: Any) -> TurnOut:
    state = _session(request, session_id)
    engine: Engine = request.app.state.engine
    store: SessionStore = request.app.state.sessions
    async with store.lock(session_id):
        result = await run_in_threadpool(engine.handle_turn, state, llm, **kw)
    return _turn_out(result)


# --- config -------------------------------------------------------------------------


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config", response_model=ConfigOut)
async def get_config(request: Request) -> ConfigOut:
    settings: Settings = request.app.state.settings
    provider: str | None = None
    model: str | None = None
    if settings.openai_api_key:
        try:
            cfg = await run_in_threadpool(resolve_provider, LLMHeaders(), settings)
            provider, model = cfg.name, cfg.model
        except InvalidProviderConfig:
            provider = settings.llm_provider
    return ConfigOut(
        has_server_key=bool(settings.openai_api_key),
        provider=provider,
        model=model,
        demo_today=today(settings).isoformat(),
        consent_scenarios=list(CONSENT_SCENARIOS),
    )


@router.post(
    "/config/validate-key", response_model=ValidateKeyOut, response_model_exclude_none=True
)
async def validate_key(body: ValidateKeyIn, request: Request) -> ValidateKeyOut:
    # The request always carries a key, so resolution never falls back to the server key.
    headers = LLMHeaders(
        api_key=body.api_key, provider=body.provider, base_url=body.base_url, model=body.model
    )
    cfg = await _resolve(headers, request.app.state.settings)
    client = request.app.state.llm_client_factory(cfg)
    try:
        await run_in_threadpool(
            lambda: client.chat([{"role": "user", "content": "ping"}], max_tokens=16)
        )
    except LLMError as e:
        return ValidateKeyOut(ok=False, error=e.kind)
    return ValidateKeyOut(ok=True)


# --- sessions -----------------------------------------------------------------------


@router.post("/sessions", response_model=SessionOut)
async def create_session(body: SessionIn, request: Request) -> SessionOut:
    store: SessionStore = request.app.state.sessions
    engine: Engine = request.app.state.engine
    state = store.create(body.consent_scenario)
    async with store.lock(state.session_id):
        result = engine.start(state)
    turn = _turn_out(result)
    return SessionOut(
        session_id=state.session_id,
        messages=turn.messages,
        state=turn.state,
        quick_replies=turn.quick_replies,
    )


@router.post("/sessions/{session_id}/messages", response_model=TurnOut)
async def post_message(session_id: str, body: MessageIn, request: Request) -> TurnOut:
    _session(request, session_id)
    cfg = await _resolve(_headers(request), request.app.state.settings)
    limiter: SlidingWindowLimiter = request.app.state.limiter
    if cfg.uses_server_key and not limiter.check(_client_ip(request), time.time()):
        raise ApiError(429, "demo_quota_exceeded")
    llm = request.app.state.llm_factory(cfg)
    return await _run_turn(request, session_id, llm, text=body.text, action=body.action)


@router.post("/sessions/{session_id}/events", response_model=TurnOut)
async def post_event(session_id: str, body: EventIn, request: Request) -> TurnOut:
    llm = request.app.state.event_bundle()
    return await _run_turn(request, session_id, llm, event=body.type)


@router.get("/sessions/{session_id}/state")
async def get_state(session_id: str, request: Request) -> dict[str, Any]:
    state = _session(request, session_id)
    async with request.app.state.sessions.lock(session_id):
        return public_snapshot(state)


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: str, request: Request) -> dict[str, Any]:
    state = _session(request, session_id)
    async with request.app.state.sessions.lock(session_id):
        return {
            "session_id": state.session_id,
            "transcript": [m.model_dump(mode="json") for m in state.transcript],
            "events": [e.model_dump(mode="json") for e in state.events],
        }


@router.get("/sessions/{session_id}/outbox")
def get_outbox(session_id: str, request: Request) -> list[dict[str, str]]:
    _session(request, session_id)
    engine: Engine = request.app.state.engine
    return engine.outbox.list(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request) -> Response:
    _session(request, session_id)
    store: SessionStore = request.app.state.sessions
    store.delete(session_id)
    return Response(status_code=204)


# --- error handling -----------------------------------------------------------------


def _api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # registered for ApiError only
        raise exc
    content: dict[str, Any] = {"code": exc.code}
    if exc.detail is not None:
        content["detail"] = exc.detail
    return JSONResponse(content, status_code=exc.status)


def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    # Location and message only: never echo the rejected input (it may hold a key).
    if not isinstance(exc, RequestValidationError):  # registered for this type only
        raise exc
    detail = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse({"code": "invalid_request", "detail": detail}, status_code=422)


class InternalErrorMiddleware:
    """Turn any unexpected exception into ``500 {"code":"internal_error"}``.

    The exception is logged (keys redacted by the log filter) and swallowed, so no
    traceback reaches the client or the server's own unfiltered error output.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if not started:
                response = JSONResponse({"code": "internal_error"}, status_code=500)
                await response(scope, receive, send)


def install_api(app: FastAPI) -> None:
    app.include_router(router)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(InternalErrorMiddleware)
