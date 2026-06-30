"""Schemas for the ``User`` resource.

These are the validated contracts for creating and reading users. Note what's
missing from the response schema (``UserRead``): the password and its hash never
cross the API boundary.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Fields common to creating and reading a user."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)


class UserCreate(UserBase):
    """Request body for registering a new account.

    The plaintext password is accepted here, checked for a sane length, and then
    hashed by the service layer; it's never stored as-is.
    """

    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Request body for logging in with email + password."""

    email: EmailStr
    password: str


class UserRead(UserBase):
    """Public representation of a user returned by the API.

    ``from_attributes=True`` lets FastAPI build this straight from a SQLAlchemy
    ``User`` instance by reading attributes off the object.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
