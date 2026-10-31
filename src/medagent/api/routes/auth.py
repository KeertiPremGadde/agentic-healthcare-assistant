"""Accounts and login (JWT).

Flow: register -> login (OAuth2 password form, so the Authorize button in /docs works) -> send
`Authorization: Bearer <token>` on every other call. The server maps the token to the user and
the user to its patient record; the patient id is never accepted from the client.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from medagent.api.accounts import UsernameTakenError, create_account, find_by_username
from medagent.api.deps import CurrentUserDep, ResourcesDep, client_ip, enforce_rate_limit
from medagent.api.errors import DEMO_NOTICE, ApiError
from medagent.api.schemas import ErrorResponse, RegisterRequest, TokenResponse, UserOut
from medagent.api.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=201,
    response_model=UserOut,
    summary="Create a demo account",
    description="Username and password only; no email or personal data is collected. "
    + DEMO_NOTICE,
    responses={409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def register(body: RegisterRequest, request: Request, res: ResourcesDep) -> UserOut:
    enforce_rate_limit(
        res, f"register:{client_ip(request)}", res.settings.register_rate_per_hour, 3600
    )
    username = body.username.lower()
    password_hash = await asyncio.to_thread(hash_password, body.password)  # Argon2 is CPU-heavy
    try:
        account = await asyncio.to_thread(
            create_account, res.session_factory, username, password_hash
        )
    except UsernameTakenError:
        raise ApiError(409, "username_taken", "That username is taken. Pick another.") from None
    return UserOut(username=account.username, patient_id=account.patient_id)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and get an access token",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, res: ResourcesDep
) -> TokenResponse:
    enforce_rate_limit(res, f"login:{client_ip(request)}", res.settings.login_rate_per_minute, 60)
    account = await asyncio.to_thread(find_by_username, res.session_factory, form.username.lower())
    stored = account.password_hash if account else None
    # Same work whether or not the user exists, and the same answer for both failure cases.
    valid = await asyncio.to_thread(verify_password, form.password, stored)
    if account is None or not valid:
        raise ApiError(
            401,
            "invalid_credentials",
            "Wrong username or password.",
            {"WWW-Authenticate": "Bearer"},
        )
    settings = res.settings
    token = create_access_token(
        account.id, settings.jwt_secret.get_secret_value(), settings.jwt_expire_minutes
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_expire_minutes * 60)


@router.get("/me", response_model=UserOut, summary="Who am I?")
async def me(user: CurrentUserDep) -> UserOut:
    return UserOut(username=user.username, patient_id=user.patient_id)
