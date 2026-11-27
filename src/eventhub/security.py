"""Password hashing, password policy and session token helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 14
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters

# Verified against when a username does not exist, so timing does not reveal valid usernames.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class PasswordPolicyError(ValueError):
    """Raised when a password does not meet the policy."""


def utcnow() -> datetime:
    """Naive UTC timestamp, matching how DATETIME columns are stored."""
    return datetime.now(UTC).replace(tzinfo=None)


def validate_password(password: str, username: str) -> None:
    """Length-based policy (NIST SP 800-63B style): long passphrases, no composition rules."""
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters"
        )
    if username.lower() in password.lower():
        raise PasswordPolicyError("Password must not contain the username")
    if len(set(password)) < 6:
        raise PasswordPolicyError("Password is too repetitive")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def new_session_token() -> str:
    """256 bits of randomness; only the SHA-256 digest is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()