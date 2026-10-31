"""Housekeeping routes so the bare URL and browsers' automatic requests don't show 404s."""

from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False)


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/docs")  # 307: keeps the method, and is not cached as permanent


@router.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)  # browsers ask for this on every site; there is no icon yet
