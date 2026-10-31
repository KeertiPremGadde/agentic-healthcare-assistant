import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from medagent import __version__
from medagent.api.deps import ResourcesDep

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the process is up")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready", summary="Readiness: the database answers")
async def ready(res: ResourcesDep) -> dict[str, str]:
    def ping() -> None:
        with res.session_factory() as session:
            session.execute(text("SELECT 1"))

    await asyncio.to_thread(ping)  # a failure becomes a 500 and the load balancer takes us out
    return {"status": "ready"}
