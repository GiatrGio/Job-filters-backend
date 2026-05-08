from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    admin,
    applications,
    billing,
    contacts,
    evaluate,
    filter_validation,
    interviews,
    me,
    profiles,
)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="LinkedIn Job Filter API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(evaluate.router)
    app.include_router(admin.router)
    app.include_router(profiles.router)
    app.include_router(filter_validation.router)
    app.include_router(applications.router)
    app.include_router(billing.router)
    app.include_router(contacts.router)
    app.include_router(interviews.router)
    app.include_router(me.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
