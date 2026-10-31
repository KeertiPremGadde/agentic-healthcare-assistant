"""Passwords and login tokens.

- Passwords: Argon2id (pwdlib). Only the hash is stored; the password is never logged.
- Tokens: signed JWTs (HS256) with `sub` (user id), `iat` and `exp`. Verification pins the
  algorithm list, so `alg: none` and algorithm-confusion tokens are rejected, and requires `exp`
  and `sub`. The patient id is NOT in the token: it is looked up server-side from the user.
"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

ALGORITHM = "HS256"
_hasher = PasswordHash((Argon2Hasher(),))
# Verified against when the username doesn't exist, so a missing user costs the same time as a
# wrong password and login can't be used to discover which usernames exist.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


class InvalidTokenError(Exception):
    """The token is malformed, expired, or its signature does not match."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-effort check: always runs one Argon2 verification."""
    return _hasher.verify(password, password_hash or _DUMMY_HASH) and password_hash is not None


def create_access_token(
    user_id: int, secret: str, expires_minutes: int, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> int:
    """Return the user id, or raise InvalidTokenError (expired, tampered, wrong algorithm...)."""
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "iat"]}
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc
