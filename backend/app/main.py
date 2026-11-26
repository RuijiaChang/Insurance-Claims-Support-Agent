from fastapi import FastAPI


def create_app(settings: object | None = None) -> FastAPI:
    """Build the FastAPI app.

    `settings` is accepted but ignored for now; Task 2 introduces the Settings class
    and wires it in here.
    """
    app = FastAPI(title="SOP Insurance Claims Support Agent")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
