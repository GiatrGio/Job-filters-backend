from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_unhandled_exceptions_return_json(settings: object) -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {
        "detail": "Internal Server Error",
        "error": "internal_server_error",
    }
