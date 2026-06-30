"""Shared pytest fixtures.

Every fixture is function-scoped so tests never share state:

    db_factory       a session factory bound to a fresh in-memory SQLite DB
    client           a TestClient whose requests and background tasks both use it
    auth_headers     a registered + logged-in user's Authorization header
    sample_pdf_bytes the bytes of a tiny, valid PDF resume
    mock_llm         replaces the LLM with deterministic canned outputs
"""

import warnings

# Silence a harmless, one-time LangChainPendingDeprecationWarning that LangGraph's
# checkpoint serializer emits the first time langgraph.checkpoint.base is imported.
# It's awkward to suppress for two reasons:
#   1. When LangChain's deprecation module loads it prepends a high-priority
#      "default" filter for this warning class, which beats any "ignore" set
#      before it (even -W ignore::PendingDeprecationWarning and the pytest.ini
#      category filters).
#   2. The import that triggers it is lazy: it happens inside the first pipeline
#      test, not when "app" is imported.
# So the order that works is: let LangChain install its filter (by importing its
# deprecation module), add our ignore on top of it, then force the lazy import now
# so the warning fires once and is swallowed. The module is cached afterwards and
# never warns again, so no test ever sees it.
import langchain_core._api.deprecation as _lc_deprecation  # 1. installs LangChain's filter

warnings.filterwarnings(  # 2. our ignore now outranks LangChain's "default" filter
    "ignore",
    message=r"The default value of `allowed_objects`",
    category=_lc_deprecation.LangChainPendingDeprecationWarning,
)
import langgraph.checkpoint.base  # noqa: F401  3. fire and swallow the one-time warning

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.agents.nodes as agent_nodes
import app.services.generation as generation
from app.core.database import Base, get_db
from app.main import app
from app.schemas import (
    CoverLetterVerification,
    FitAnalysis,
    InterviewPrep,
    InterviewQuestion,
    ResumeBulletRewrite,
    ResumeRewrite,
)


def _make_pdf(text: str) -> bytes:
    """Build the bytes of a minimal, valid single-page PDF containing ``text``.

    Computing the cross-reference offsets by hand keeps the test dependency-free
    (no reportlab/fpdf needed) while still producing a PDF pypdf can read.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    content_stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objects.append(b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n" + content_stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = b"%PDF-1.4\n"
    byte_offsets = []
    for index, body in enumerate(objects, start=1):
        byte_offsets.append(len(pdf))
        pdf += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_position = len(pdf)
    entry_count = len(objects) + 1  # +1 for the mandatory free object 0
    pdf += b"xref\n0 " + str(entry_count).encode() + b"\n0000000000 65535 f \n"
    for offset in byte_offsets:
        pdf += ("%010d 00000 n \n" % offset).encode()
    pdf += (
        b"trailer\n<< /Size " + str(entry_count).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_position).encode() + b"\n%%EOF"
    )
    return pdf


@pytest.fixture()
def db_factory():
    """Yield a session factory bound to a fresh in-memory SQLite database.

    A ``StaticPool`` keeps every session on one shared connection, so the
    request session and the background-task session see the same in-memory data.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestSession
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_factory, monkeypatch):
    """A TestClient whose request sessions AND background tasks use the test DB."""

    def override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Background generation opens its own session via SessionLocal; point that at
    # the very same in-memory database the requests use.
    monkeypatch.setattr(generation, "SessionLocal", db_factory)

    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    """Register + log in a user and return ready-to-use Authorization headers."""
    credentials = {"email": "tester@example.com", "password": "supersecret123"}
    client.post("/auth/register", json=credentials)
    token = client.post("/auth/login", json=credentials).json()["access_token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def sample_pdf_bytes():
    """The bytes of a tiny, valid PDF resume."""
    return _make_pdf("Built APIs. Led a team of four engineers.")


@pytest.fixture()
def mock_llm(monkeypatch):
    """Replace the LLM with a fake that returns deterministic structured outputs.

    Patches ``get_chat_model`` in the agent-nodes module so the whole pipeline runs
    in isolation, with no network and no API key.
    """

    class _FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, _messages):
            if self.schema is FitAnalysis:
                return FitAnalysis(
                    met_requirements=["Python", "FastAPI"],
                    missing_requirements=["Kubernetes"],
                    points_to_emphasize=["API design"],
                    overall_summary="Strong fit.",
                    fit_score=80,
                )
            if self.schema is ResumeRewrite:
                return ResumeRewrite(
                    bullets=[
                        ResumeBulletRewrite(
                            section="Experience",
                            original_bullet="Built APIs.",
                            rewritten_bullet="Architected FastAPI services handling 1M requests/day.",
                            rationale="Adds JD keyword + quantified impact.",
                        )
                    ],
                    summary_of_changes="Quantified impact.",
                )
            if self.schema is InterviewPrep:
                return InterviewPrep(
                    questions=[
                        InterviewQuestion(
                            question="Question %d?" % i,
                            sample_answer="Answer %d." % i,
                            grounded_in="Built APIs.",
                        )
                        for i in range(1, 11)
                    ]
                )
            if self.schema is CoverLetterVerification:
                # Default: the canned cover letter is fully grounded, so the
                # Governor proceeds without looping.
                return CoverLetterVerification(has_unsupported_claims=False, unsupported_claims=[])
            raise AssertionError("Unexpected schema: %r" % (self.schema,))

    class _FakeChat:
        def with_structured_output(self, schema, **_kwargs):
            return _FakeStructured(schema)

        def invoke(self, _messages):
            return AIMessage(content="Dear Hiring Manager,\n\nI am excited to apply...\n\nSincerely,\nA. Candidate")

    monkeypatch.setattr(agent_nodes, "get_chat_model", lambda: _FakeChat())


@pytest.fixture()
def completed_role(client, auth_headers, sample_pdf_bytes, mock_llm):
    """Create a role, run the (mocked) pipeline to completion, and return its ids.

    Yields ``{"role_id", "draft_id"}`` for a role whose draft is COMPLETED with all
    four artifacts, which is the precondition for the analysis endpoints.
    """
    import time

    files = {"resume_pdf": ("resume.pdf", sample_pdf_bytes, "application/pdf")}
    data = {
        "job_title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "jd_text": "Seeking a FastAPI engineer with SQL.",
    }
    body = client.post("/roles", data=data, files=files, headers=auth_headers).json()
    draft_id = body["draft_id"]
    for _ in range(50):
        if client.get("/drafts/%d" % draft_id, headers=auth_headers).json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    return {"role_id": body["role"]["id"], "draft_id": draft_id}
