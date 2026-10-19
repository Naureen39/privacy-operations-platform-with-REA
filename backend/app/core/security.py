"""Password hashing, access tokens and refresh token helpers."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.db.enums import Role

_hasher = PasswordHasher()  # argon2id with the library's recommended parameters
ALGORITHM = "HS256"


class WeakPasswordError(ValueError):
    pass


class TokenError(Exception):
    pass


def validate_password_strength(password: str, min_length: int = 12) -> None:
    if len(password) < min_length:
        raise WeakPasswordError(f"Password must be at least {min_length} characters long")


def hash_password(password: str, min_length: int = 12) -> str:
    validate_password_strength(password, min_length)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Verified when the account does not exist, so that response time does not reveal it.
DUMMY_PASSWORD_HASH = _hasher.hash("timing-equalisation-password")


@dataclass(frozen=True)
class Claims:
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str


def create_access_token(
    secret: str,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    role: Role,
    minutes: int,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role.value,
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": issued,
        "exp": issued + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(secret: str, token: str) -> Claims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "org", "typ"]},
        )
        if payload["typ"] != "access":
            raise TokenError("wrong token type")
        return Claims(uuid.UUID(payload["sub"]), uuid.UUID(payload["org"]), str(payload["role"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise TokenError("invalid token") from exc


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens carry 384 bits of entropy, so a plain SHA-256 is sufficient."""
    return hashlib.sha256(token.encode()).hexdigest()
