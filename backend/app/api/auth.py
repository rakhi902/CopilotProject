"""Authentication endpoints: register, login, and "who am I".

These routes are deliberately thin: they validate input via schemas, do the
minimal database work through small local helpers, and lean on
``app.core.security`` for all the hashing and token logic.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas import Token, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Return the user with this email, or ``None`` if there isn't one."""
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    """Register a new account.

    Takes the new user's email, optional full name, and plaintext password.
    Returns the created user as a safe ``UserRead`` (no password fields). Raises
    409 if the email is already registered.
    """
    if _get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),  # never store the plaintext
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # reload DB-generated fields (id, timestamps) onto the object
    return user


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    """Exchange email + password for a JWT access token.

    Raises 401 if the email is unknown or the password is wrong (the message is
    intentionally vague so it never reveals which one failed), and 403 if the
    account has been deactivated.
    """
    user = _get_user_by_email(db, payload.email)
    # We return one identical error whether the user is missing or the password is
    # wrong, so we never leak which half failed.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    access_token = create_access_token(subject=user.id)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Return the profile of the currently authenticated user."""
    return current_user
