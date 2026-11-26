from fastapi import FastAPI

from app.data.repo import load_repo
from app.settings import Settings, get_settings, load_sop_config


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app, attaching settings, SOP config and the fixture repo to state."""
    settings = settings or get_settings()
    app = FastAPI(title="SOP Insurance Claims Support Agent")
    app.state.settings = settings
    app.state.sop = load_sop_config(settings.sop_config_path)
    app.state.repo = load_repo(settings.fixtures_dir)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
