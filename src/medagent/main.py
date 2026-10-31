"""FastAPI application entry point.

    uv run python scripts/serve.py        # http://localhost:8000/docs  (and /demo in local mode)

`create_app()` builds the real resources (MCP session, Postgres checkpointer, LLM) in the
lifespan. Tests pass ready-made `Resources` (fake LLM, in-memory checkpointer) instead.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medagent import __version__
from medagent.api.errors import DEMO_NOTICE, register_error_handlers
from medagent.api.middleware import RequestIdMiddleware
from medagent.api.resources import Resources, open_resources
from medagent.api.routes import appointments, auth, chat, demo, health
from medagent.core.config import Settings, get_settings
from medagent.core.logging import configure_logging

DESCRIPTION = f"""
An agentic healthcare assistant: cited medical answers, specialist suggestions and booking with
confirmation. **{DEMO_NOTICE}**

**Try it here:** register (`POST /v1/auth/register`), click **Authorize** and enter the same
username and password, then use `POST /v1/chat` with `stream=false`. If it asks you to confirm a
booking, answer with `POST /v1/chat/{{conversation_id}}/resume`.

Not medical advice. In an emergency call 112 (EU) or 911 (US).
"""

TAGS = [
    {"name": "auth", "description": "Create a demo account and log in (JWT)."},
    {"name": "chat", "description": "Talk to the assistant; streams progress over SSE."},
    {"name": "appointments", "description": "Your own appointments."},
    {"name": "health", "description": "Liveness and readiness."},
]


def create_app(resources: Resources | None = None, settings: Settings | None = None) -> FastAPI:
    settings = resources.settings if resources else (settings or get_settings())
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_resources(settings) as opened:
            app.state.resources = opened
            yield

    app = FastAPI(
        title="MedAgent API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=None if resources else lifespan,
    )
    if resources:
        app.state.resources = resources
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        allow_credentials=False,  # auth is a Bearer header, not a cookie: no CSRF surface
    )
    app.add_middleware(RequestIdMiddleware)  # outermost: ids on every response, even errors
    for router in (health.router, auth.router, chat.router, appointments.router):
        app.include_router(router)
    if settings.app_env == "local":
        app.include_router(demo.router)
    return app


app = create_app()
