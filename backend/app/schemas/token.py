"""Schemas describing JWT access tokens.

``Token`` is the JSON the login endpoint returns; ``TokenPayload`` is the set of
decoded claims carried inside a token. The signing logic that produces them lives
in ``app.core.security``.
"""

from typing import Optional

from pydantic import BaseModel


class Token(BaseModel):
    """The response body returned after a successful login."""

    access_token: str
    token_type: str = "bearer"   # the scheme the client uses in the Authorization header


class TokenPayload(BaseModel):
    """The decoded claims of a JWT access token.

    ``sub`` is the subject claim, the authenticated user's id stored as a string
    per the JWT spec. ``exp`` is the expiry claim, a POSIX timestamp after which
    the token is no longer valid.
    """

    sub: Optional[str] = None
    exp: Optional[int] = None
