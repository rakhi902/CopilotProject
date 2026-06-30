"""Tests for password hashing and JWT access tokens (app.core.security)."""

from datetime import timedelta

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_not_plaintext_and_verifies():
    hashed = hash_password("supersecret123")
    assert hashed != "supersecret123"
    assert verify_password("supersecret123", hashed)
    assert not verify_password("the-wrong-password", hashed)


def test_password_longer_than_bcrypt_72_byte_limit_does_not_crash():
    # bcrypt only considers the first 72 bytes; our truncation must keep
    # hashing and verification consistent rather than raising.
    long_password = "A" * 200
    assert verify_password(long_password, hash_password(long_password))


def test_access_token_round_trips_the_subject():
    token = create_access_token(subject=7, expires_delta=timedelta(minutes=5))
    assert decode_access_token(token).sub == "7"


def test_tampered_token_is_rejected():
    token = create_access_token(subject=7)
    with pytest.raises(JWTError):
        decode_access_token(token + "tampered")


def test_expired_token_is_rejected():
    expired = create_access_token(subject=7, expires_delta=timedelta(seconds=-1))
    with pytest.raises(JWTError):
        decode_access_token(expired)
