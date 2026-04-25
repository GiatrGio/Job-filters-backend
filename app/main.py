from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langfuse.decorators import langfuse_context

from app.config import get_settings
from app.routers import evaluate, me, profiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Flush queued observations so short-lived processes (CI, Fly restarts)
    # don't drop the last few traces. No-op when Langfuse isn't configured.
    try:
        langfuse_context.flush()
    except Exception:
        # Never let observability teardown fail the shutdown path.
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # Configure Langfuse. Pydantic-settings reads .env into the Settings
    # object but does not export the values into os.environ, which is what
    # the Langfuse SDK's auto-config consults. We set both:
    #   1. os.environ — used by the SDK's singleton client on lazy init
    #   2. langfuse_context.configure(...) — used by the decorator path
    # Then we run auth_check() so the uvicorn log makes it obvious whether
    # the keys are valid.
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        langfuse_context.configure(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        try:
            from langfuse import Langfuse

            probe = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            ok = probe.auth_check()
            logger.info(
                "Langfuse configured host=%s auth_ok=%s public_key_prefix=%s",
                settings.langfuse_host,
                ok,
                settings.langfuse_public_key[:10],
            )
        except Exception as exc:
            logger.warning("Langfuse auth check failed: %s", exc)
    else:
        logger.info(
            "Langfuse disabled (keys empty): public_key_set=%s secret_key_set=%s",
            bool(settings.langfuse_public_key),
            bool(settings.langfuse_secret_key),
        )

    app = FastAPI(
        title="LinkedIn Job Filter API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(evaluate.router)
    app.include_router(profiles.router)
    app.include_router(me.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/debug/langfuse", tags=["debug"])
    def debug_langfuse() -> dict:
        """Create a trace using the low-level Langfuse client, bypassing the
        @observe decorator. If this shows up in the UI but our provider
        traces don't, the problem is the decorator integration, not the SDK.
        """
        from langfuse import Langfuse

        lf = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        trace = lf.trace(name="debug_manual_trace", input={"note": "diagnostic"})
        trace.generation(
            name="debug_manual_generation",
            model="debug-model",
            input=[{"role": "user", "content": "diagnostic ping"}],
            output={"pong": True},
            usage={"input": 1, "output": 1},
        )
        lf.flush()
        return {
            "ok": True,
            "trace_id": trace.id,
            "host": settings.langfuse_host,
        }

    return app


app = create_app()
