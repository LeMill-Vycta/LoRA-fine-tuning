from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.core.config import get_settings

try:
    import bcrypt
except Exception:  # pragma: no cover - optional dependency in some deploys
    bcrypt = None

ALGORITHM = "HS256"
_PASSWORD_POLICY = re.compile(r"^(?=.*[a-zA-Z])(?=.*\d).{8,128}$")
_PBKDF2_PREFIX = "pbkdf2_sha256"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> tuple[bool, str | None]:
    if not _PASSWORD_POLICY.match(password):
        return False, "Password must be 8+ chars with at least one letter and one number."
    return True, None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith(f"{_PBKDF2_PREFIX}$"):
        return _verify_pbkdf2_password(plain_password, hashed_password)
    return _verify_legacy_bcrypt_password(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    settings = get_settings()
    iterations = settings.password_pbkdf2_iterations
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"{_PBKDF2_PREFIX}$"
        f"{iterations}$"
        f"{_b64encode(salt)}$"
        f"{_b64encode(derived)}"
    )


def password_needs_rehash(hashed_password: str) -> bool:
    if not hashed_password.startswith(f"{_PBKDF2_PREFIX}$"):
        return True
    parsed = _parse_pbkdf2_hash(hashed_password)
    if not parsed:
        return True
    iterations, _, _ = parsed
    return iterations < get_settings().password_pbkdf2_iterations


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(tz=UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.session_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}")


def _parse_pbkdf2_hash(hashed_password: str) -> tuple[int, bytes, bytes] | None:
    try:
        scheme, iter_raw, salt_raw, digest_raw = hashed_password.split("$", 3)
        if scheme != _PBKDF2_PREFIX:
            return None
        iterations = int(iter_raw)
        if iterations <= 0:
            return None
        salt = _b64decode(salt_raw)
        digest = _b64decode(digest_raw)
    except (ValueError, binascii.Error):
        return None
    return iterations, salt, digest


def _verify_pbkdf2_password(plain_password: str, hashed_password: str) -> bool:
    parsed = _parse_pbkdf2_hash(hashed_password)
    if not parsed:
        return False
    iterations, salt, expected_digest = parsed
    candidate = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected_digest)


def _verify_legacy_bcrypt_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password.startswith("$2"):
        return False
    if bcrypt is None:
        return False
    try:
        # bcrypt truncates inputs beyond 72 bytes by design; retained only for legacy hash migration.
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False
