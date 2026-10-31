"""Shared request dependencies: resources, the logged-in user, and rate limiting."""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from medagent.api.accounts import find_by_id
from medagent.api.errors import ApiError
from medagent.api.resources import Resources
from medagent.api.security import InvalidTokenError, decode_access_token

# auto_error=False so a missing token produces OUR error envelope, not FastAPI's default.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login", auto_error=False)

_BEARER = {"WWW-Authenticate": "Bearer"}


def get_resources(request: Request) -> Resources:
    resources: Resources | None = getattr(request.app.state, "resources", None)
    if resources is None:
        raise ApiError(503, "not_ready", "The service is starting up. Try again in a moment.")
    return resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    patient_id: int  # looked up from the account, never taken from the request


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)], res: ResourcesDep
) -> CurrentUser:
    if token is None:
        raise ApiError(401, "not_authenticated", "Log in to use this endpoint.", _BEARER)
    try:
        user_id = decode_access_token(token, res.settings.jwt_secret.get_secret_value())
    except InvalidTokenError:
        raise ApiError(
            401, "invalid_token", "Your login is invalid or has expired.", _BEARER
        ) from None
    account = await asyncio.to_thread(find_by_id, res.session_factory, user_id)
    if account is None:  # token for a deleted account
        raise ApiError(401, "invalid_token", "Your login is invalid or has expired.", _BEARER)
    return CurrentUser(account.id, account.username, account.patient_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def client_ip(request: Request) -> str:
    """The peer address. Behind a reverse proxy (Phase 8) this is the proxy's address unless
    uvicorn runs with --proxy-headers and a trusted --forwarded-allow-ips."""
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(res: Resources, key: str, limit: int, window_seconds: float) -> None:
    allowed, retry_after = res.limiter.allow(key, limit, window_seconds)
    if not allowed:
        wait = max(1, int(retry_after) + 1)
        raise ApiError(
            429,
            "rate_limited",
            f"Too many requests. Try again in {wait} seconds.",
            {"Retry-After": str(wait)},
        )
