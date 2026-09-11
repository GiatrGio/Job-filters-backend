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


def test_cors_preflight_allows_put(settings: object) -> None:
    client = TestClient(create_app())

    resp = client.options(
        "/cover-letter/settings",
        headers={
            "Origin": "chrome-extension://fake",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert resp.status_code == 200
    assert "PUT" in resp.headers["access-control-allow-methods"]
    assert resp.headers["access-control-allow-origin"] == "chrome-extension://fake"
