from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok() -> None:
    assert TestClient(create_app()).get("/api/health").json() == {"status": "ok"}
