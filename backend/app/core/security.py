"""Password hashing and JWT access tokens.

This module knows nothing about HTTP or FastAPI; it works only with strings and
times. Turning a failure here (say, an expired token) into an HTTP 401 is the
job of the dependency layer in ``app.core.deps``.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from jose import JWTError, jwt  # noqa: F401  (JWTError re-exported for callers/tests)
from passlib.context import CryptContext

from app.core.config import get_settings
from app.schemas.token import TokenPayload

settings = get_settings()

# One reusable hashing context. bcrypt is a slow, salted algorithm, which is
# exactly what passwords want. deprecated="auto" lets us transparently re-hash
# with a newer scheme if we ever change the list of schemes.
_password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt only looks at the first 72 bytes of a password. We truncate to that
# limit ourselves (rather than let the backend do it silently or raise) so
# hashing and verification always run on identical input.
_BCRYPT_MAX_BYTES = 72


def _encode_for_bcrypt(plain_password: str) -> bytes:
    """Encode a password to UTF-8 and truncate it to bcrypt's 72-byte limit."""
    return plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password into a salted bcrypt hash for storage."""
    return _password_context.hash(_encode_for_bcrypt(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash.

    Returns ``True`` on a match, ``False`` otherwise, including when the stored
    hash is malformed, so a bad row can never crash a login.
    """
    try:
        return _password_context.verify(_encode_for_bcrypt(plain_password), hashed_password)
    except ValueError:
        return False


def create_access_token(subject: Union[str, int], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token for a user.

    ``subject`` is the user's id; it's coerced to ``str`` because the JWT ``sub``
    claim is specified as a string. ``expires_delta`` overrides the configured
    ``ACCESS_TOKEN_EXPIRE_MINUTES`` lifetime when given.
    """
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    claims = {
        "sub": str(subject),                 # who the token is about
        "iat": int(issued_at.timestamp()),   # issued-at timestamp
        "exp": int(expires_at.timestamp()),  # expiry; jose enforces it on decode
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT access token.

    Verifies the signature and the expiry, then checks the decoded claim shape
    against ``TokenPayload``. Raises ``JWTError`` if the token is malformed,
    tampered with, or expired; the dependency layer catches that and returns a
    401.
    """
    raw_claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return TokenPayload(**raw_claims)
