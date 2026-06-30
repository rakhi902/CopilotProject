"""Pydantic schemas: the validated data contracts that cross the API boundary.

Re-exports the concrete schemas so callers can write
``from app.schemas import UserCreate`` without knowing which module each one
lives in.
"""

from app.schemas.analysis import (
    ATSScore,
    InterviewGrade,
    InterviewGradeRequest,
    NegotiationScript,
    SalaryCoachRequest,
    SalaryCoaching,
)
from app.schemas.draft import (
    ArtifactRegenerationResponse,
    CoverLetterVerification,
    DraftRead,
    DraftStatusRead,
    FitAnalysis,
    InterviewPrep,
    InterviewQuestion,
    ResumeBulletRewrite,
    ResumeRewrite,
)
from app.schemas.role import (
    RoleBase,
    RoleBulkDeleteRequest,
    RoleBulkDeleteResponse,
    RoleCreate,
    RoleRead,
    RoleStatusUpdate,
    RoleSubmissionResponse,
)
from app.schemas.token import Token, TokenPayload
from app.schemas.user import UserBase, UserCreate, UserLogin, UserRead

__all__ = [
    # user
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserRead",
    # token
    "Token",
    "TokenPayload",
    # role
    "RoleBase",
    "RoleCreate",
    "RoleRead",
    "RoleSubmissionResponse",
    "RoleStatusUpdate",
    "RoleBulkDeleteRequest",
    "RoleBulkDeleteResponse",
    # draft + the four artifact schemas
    "DraftRead",
    "DraftStatusRead",
    "FitAnalysis",
    "ResumeRewrite",
    "ResumeBulletRewrite",
    "InterviewPrep",
    "InterviewQuestion",
    # cover-letter fact-check (the Governor)
    "CoverLetterVerification",
    # per-artifact regeneration
    "ArtifactRegenerationResponse",
    # extra analysis (ATS / interview grade / salary coach)
    "ATSScore",
    "InterviewGradeRequest",
    "InterviewGrade",
    "SalaryCoachRequest",
    "NegotiationScript",
    "SalaryCoaching",
]
