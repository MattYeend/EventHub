import pytest

from eventhub.security import (
    PasswordPolicyError,
    hash_password,
    hash_token,
    new_session_token,
    validate_password,
    verify_password,
)


def test_hash_round_trip_uses_argon2id():
    hashed = hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct-horse-battery") is True
    assert verify_password(hashed, "wrong-horse-battery!") is False


def test_verify_rejects_a_malformed_hash_without_raising():
    assert verify_password("not-a-hash", "anything") is False


@pytest.mark.parametrize(
    "password",
    ["short", "x" * 129, "alice-is-the-best-user", "aaaaaaaaaaaaaaaa"],
)
def test_weak_passwords_are_rejected(password):
    with pytest.raises(PasswordPolicyError):
        validate_password(password, "alice")


def test_long_passphrase_is_accepted():
    validate_password("correct-horse-battery", "alice")


def test_tokens_are_unique_and_hash_to_32_bytes():
    first, second = new_session_token(), new_session_token()
    assert first != second
    assert len(hash_token(first)) == 32
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != hash_token(second)
