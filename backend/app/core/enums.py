"""Enumerations shared by both the ORM models and the API schemas.

Keeping these in a dependency-free module lets ``app.models`` and ``app.schemas``
agree on the same set of string values without importing each other, which would
risk a circular import.
"""

from enum import Enum


class DraftStatus(str, Enum):
    """Where a Draft is in the generation pipeline.

    Inheriting from ``str`` means the members serialize to plain strings in JSON
    and store as plain strings in the database, while the code still has one
    authoritative list of valid states to reference.
    """

    PENDING = "pending"        # row created, pipeline hasn't started
    PROCESSING = "processing"  # the LangGraph agents are running
    COMPLETED = "completed"    # all artifacts generated and saved
    FAILED = "failed"          # the pipeline raised; see Draft.error_message


class ApplicationStatus(str, Enum):
    """The user-managed status of a job application.

    This is separate from :class:`DraftStatus`, which tracks generation. This one
    is the state a user sets by hand in the UI to track where an application
    stands. The member values are the exact labels shown to users.
    """

    NOT_APPLIED = "Not Applied"    # default: kit generated, not yet submitted
    APPLIED = "Applied"            # the user has submitted this application
    INTERVIEWING = "Interviewing"  # in the interview process
    REJECTED = "Rejected"          # the application was turned down
