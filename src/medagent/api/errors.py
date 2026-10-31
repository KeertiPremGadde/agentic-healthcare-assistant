"""One error shape for the whole API: {"error": {"code", "message", "request_id"}}.

Messages are written for end users. Handlers never include stack traces, internal exception
text, or the request body: FastAPI's default 422 echoes the offending *input* back, which for
the register endpoint would send the user's password back in the response, so it is stripped.
"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

DEMO_NOTICE = (
    "This is a demo with synthetic data. Do not enter real personal or health information."
)


class ApiError(HTTPException):
    """HTTPException with a stable machine-readable `code`."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=dict(headers or {}))
        self.code = code


_DEFAULT_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def request_id_of(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


def error_response(
    request: Request, status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id_of(request)}}
    return JSONResponse(body, status_code=status, headers=dict(headers or {}))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, str(exc.detail), exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _DEFAULT_CODES.get(exc.status_code, "error")
        return error_response(request, exc.status_code, code, str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field names and reasons only: never `input` (it can contain the password).
        problems: list[dict[str, Any]] = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "reason": e["msg"]}
            for e in exc.errors()
        ]
        summary = "; ".join(f"{p['field'] or 'request'}: {p['reason']}" for p in problems)
        return error_response(request, 422, "validation_error", f"Invalid request: {summary}")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", extra={"error": type(exc).__name__})  # type only, no text
        return error_response(request, 500, "internal_error", "Something went wrong on our side.")
