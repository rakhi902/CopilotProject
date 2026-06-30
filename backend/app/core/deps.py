"""Reusable FastAPI dependencies for authentication.

The main one is ``get_current_user``: add it to any endpoint to require a valid
JWT and receive the matching ``User`` row, or an automatic 401 if the caller
isn't authenticated. (The database-session dependency, ``get_db``, lives in
``app.core.database``.)
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

# Pull the token out of the "Authorization: Bearer <token>" header and document
# the scheme in the OpenAPI docs (this is what adds Swagger's "Authorize" button).
_bearer_scheme = HTTPBearer(auto_error=True)

# One reusable 401 meaning "we couldn't authenticate this request". The
# WWW-Authenticate header is the standard hint for bearer-token auth.
_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate authentication credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the request's bearer token.

    Use it as ``current_user: User = Depends(get_current_user)`` on any protected
    endpoint. Raises 401 if the token is missing, invalid, or expired, or its
    user no longer exists; 403 if the account has been deactivated.
    """
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except JWTError:
        # Covers a bad signature, a malformed token, and an expired token.
        raise _credentials_exception

    if payload.sub is None:
        raise _credentials_exception

    # The subject is the user's id, stored as a string inside the token.
    try:
        user_id = int(payload.sub)
    except (TypeError, ValueError):
        raise _credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise _credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )
    return user
