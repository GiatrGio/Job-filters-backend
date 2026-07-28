from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def preflight(client: TestClient, origin: str) -> int:
    resp = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    return resp.status_code


@pytest.fixture
def cors_env(monkeypatch: pytest.MonkeyPatch):
    def configure(origins: str, origin_regex: str) -> TestClient:
        monkeypatch.setenv("ALLOWED_ORIGINS", origins)
        monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", origin_regex)
        get_settings.cache_clear()
        return TestClient(create_app())

    yield configure
    get_settings.cache_clear()


def test_cors_regex_allows_any_local_dev_port(cors_env) -> None:
    client = cors_env("chrome-extension://fake", r"^http://(localhost|127\.0\.0\.1):\d+$")

    assert preflight(client, "http://127.0.0.1:55000") == 200
    assert preflight(client, "http://localhost:3000") == 200
    assert preflight(client, "chrome-extension://fake") == 200


def test_cors_regex_still_rejects_other_origins(cors_env) -> None:
    client = cors_env("chrome-extension://fake", r"^http://(localhost|127\.0\.0\.1):\d+$")

    # Anchored, so a host that merely embeds a local one is not a match.
    assert preflight(client, "https://evil.example.com") == 400
    assert preflight(client, "http://127.0.0.1.evil.com") == 400
    assert preflight(client, "https://localhost:3000") == 400


def test_cors_regex_alone_does_not_open_up_every_origin(cors_env) -> None:
    client = cors_env("", r"^http://localhost:\d+$")

    assert preflight(client, "http://localhost:3000") == 200
    assert preflight(client, "https://evil.example.com") == 400


def test_cors_falls_back_to_wildcard_when_unconfigured(cors_env) -> None:
    client = cors_env("", "")

    assert preflight(client, "https://anything.example.com") == 200


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
