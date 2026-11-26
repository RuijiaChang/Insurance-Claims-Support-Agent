from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import install_key_redaction
from app.api.ratelimit import SlidingWindowLimiter
from app.api.routes import install_api, template_bundle
from app.api.sessions import SessionStore
from app.data.repo import load_repo
from app.llm.base import LLMBundle
from app.llm.client import LLMClient, ProviderConfig
from app.llm.factory import build_llm
from app.settings import Settings, get_settings, load_sop_config, today
from app.sop.engine import Engine
from app.tools.email import Outbox

DEV_ORIGINS = ["http://localhost:5173"]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app and attach its collaborators to ``app.state``.

    ``llm_factory`` (ProviderConfig -> LLMBundle), ``llm_client_factory`` (for key
    validation) and ``event_bundle`` are plain attributes so tests can replace them.
    """
    install_key_redaction()
    settings = settings or get_settings()
    app = FastAPI(title="SOP Insurance Claims Support Agent")
    sop = load_sop_config(settings.sop_config_path)
    repo = load_repo(settings.fixtures_dir)
    app.state.settings = settings
    app.state.sop = sop
    app.state.repo = repo
    app.state.engine = Engine(repo, sop, today(settings), Outbox(settings.outbox_dir))
    app.state.sessions = SessionStore(sop.session.ttl_min)
    app.state.limiter = SlidingWindowLimiter(
        per_ip_per_min=sop.ratelimit.per_ip_per_min,
        per_ip_per_day=sop.ratelimit.per_ip_per_day,
        global_per_day=sop.ratelimit.global_per_day,
    )

    def llm_factory(cfg: ProviderConfig) -> LLMBundle:
        return build_llm(cfg, sop, repo)

    app.state.llm_factory = llm_factory
    app.state.llm_client_factory = LLMClient
    app.state.event_bundle = template_bundle

    install_api(app)
    # Added last so it wraps everything, including 500 responses from the error middleware.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-OpenAI-Key",
            "X-LLM-Provider",
            "X-LLM-Base-URL",
            "X-LLM-Model",
        ],
    )
    # Mounted after the API routes, so /api/* always wins over static files.
    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
