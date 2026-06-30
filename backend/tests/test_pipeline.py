"""Tests for the LangGraph multi-agent pipeline (app.services.agents)."""

import pytest

from app.core.config import get_settings
from app.services.agents.graph import run_pipeline


def test_pipeline_produces_all_artifacts(mock_llm):
    final_state = run_pipeline(
        resume_text="Built APIs. Led a team of 4.",
        jd_text="Seeking a FastAPI engineer. Kubernetes a plus.",
        job_title="Senior Backend Engineer",
        company="Acme Corp",
    )
    assert final_state["errors"] == []
    assert final_state["fit_analysis"]["fit_score"] == 80
    assert final_state["resume_rewrite"]["bullets"][0]["rewritten_bullet"].startswith("Architected FastAPI")
    assert final_state["cover_letter"].startswith("Dear Hiring Manager")
    assert len(final_state["interview_qa"]["questions"]) == 10


def test_pipeline_degrades_gracefully_without_an_api_key():
    # With no provider key configured, every agent should fail gracefully
    # (record an error and return None) instead of crashing the pipeline.
    settings = get_settings()
    key_is_configured = (
        (settings.llm_provider == "groq" and settings.groq_api_key)
        or (settings.llm_provider == "openai" and settings.openai_api_key)
    )
    if key_is_configured:
        pytest.skip("An LLM API key is configured; skipping the no-key degradation test.")

    final_state = run_pipeline(resume_text="Built APIs.", jd_text="FastAPI role.", job_title="Engineer", company="Acme")
    assert final_state["fit_analysis"] is None
    assert final_state["resume_rewrite"] is None
    assert final_state["interview_qa"] is None
    assert len(final_state["errors"]) >= 1


# ---------------------------------------------------------------------------
# The Governor: cover-letter self-correction loop
# ---------------------------------------------------------------------------
def _make_scripted_llm(letters, verdicts, counters):
    """Build a deterministic fake chat model that drives the cover-letter loop.

    The Fit/Resume/Interview agents get fixed, valid artifacts. The cover-letter
    plain ``.invoke`` returns ``letters`` in order; the ``CoverLetterVerification``
    structured call returns ``verdicts`` in order (each list repeats its last item
    once exhausted). ``counters`` records how many drafts and verifications ran.
    Only the cover letter uses a plain ``.invoke`` and only the verifier uses the
    ``CoverLetterVerification`` schema, so the counts are unambiguous.
    """
    from langchain_core.messages import AIMessage

    from app.schemas import (
        CoverLetterVerification,
        FitAnalysis,
        InterviewPrep,
        InterviewQuestion,
        ResumeBulletRewrite,
        ResumeRewrite,
    )

    def _take(sequence, index):
        return sequence[index] if index < len(sequence) else sequence[-1]

    class _Structured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, _messages):
            if self.schema is FitAnalysis:
                return FitAnalysis(
                    met_requirements=["FastAPI"],
                    missing_requirements=["React.js"],
                    points_to_emphasize=["High-throughput API design"],
                    overall_summary="Strong backend fit; lacks React.",
                    fit_score=65,
                )
            if self.schema is ResumeRewrite:
                return ResumeRewrite(
                    bullets=[
                        ResumeBulletRewrite(
                            section="Experience",
                            original_bullet="Built APIs.",
                            rewritten_bullet="Architected high-throughput FastAPI services.",
                            rationale="Surfaces JD keywords.",
                        )
                    ],
                    summary_of_changes="Quantified impact.",
                )
            if self.schema is InterviewPrep:
                return InterviewPrep(
                    questions=[
                        InterviewQuestion(question="Q%d?" % i, sample_answer="A%d." % i, grounded_in="Built APIs.")
                        for i in range(1, 11)
                    ]
                )
            if self.schema is CoverLetterVerification:
                verdict = _take(verdicts, counters["verify"])
                counters["verify"] += 1
                return verdict
            raise AssertionError("Unexpected schema: %r" % (self.schema,))

    class _Chat:
        def with_structured_output(self, schema, **_kwargs):
            return _Structured(schema)

        def invoke(self, _messages):
            letter = _take(letters, counters["draft"])
            counters["draft"] += 1
            return AIMessage(content=letter)

    return _Chat()


def test_cover_letter_self_correction_removes_hallucination(monkeypatch):
    """The Governor loops back once to strip a hallucinated skill, then proceeds."""
    import app.services.agents.nodes as agent_nodes

    from app.schemas import CoverLetterVerification

    counters = {"draft": 0, "verify": 0}
    letters = [
        "Dear Hiring Manager,\n\nWith 5 years of React.js experience, I would thrive...",  # hallucinated
        "Dear Hiring Manager,\n\nMy FastAPI architecture mastery makes adopting the UI layer trivial...",  # grounded
    ]
    verdicts = [
        CoverLetterVerification(has_unsupported_claims=True, unsupported_claims=["5 years of React.js experience"]),
        CoverLetterVerification(has_unsupported_claims=False, unsupported_claims=[]),
    ]
    monkeypatch.setattr(agent_nodes, "get_chat_model", lambda: _make_scripted_llm(letters, verdicts, counters))

    final = run_pipeline(
        resume_text="Built high-throughput APIs with FastAPI.",
        jd_text="Seeking a React.js engineer.",
        job_title="Frontend Engineer",
        company="Acme Corp",
    )

    # Exactly one corrective loop: two drafts, two verifications.
    assert counters["draft"] == 2
    assert counters["verify"] == 2
    assert final["cover_letter_attempts"] == 2
    # The final letter is the grounded rewrite, not the hallucinated first draft.
    assert "5 years of React.js" not in final["cover_letter"]
    assert "trivial" in final["cover_letter"]
    assert final["cover_letter_hallucinations"] == []
    # The parallel branch + fan-in still delivered every other artifact.
    assert final["resume_rewrite"] is not None
    assert len(final["interview_qa"]["questions"]) == 10
    assert final["errors"] == []


def test_cover_letter_governor_caps_retries_and_never_loops_forever(monkeypatch):
    """If every draft keeps hallucinating, the loop still stops at the attempt cap."""
    import app.services.agents.nodes as agent_nodes

    from app.schemas import CoverLetterVerification

    counters = {"draft": 0, "verify": 0}
    # The letter is always hallucinated and the verifier always flags it.
    letters = ["Dear Hiring Manager,\n\nI am a world-renowned expert in an invented skill..."]
    verdicts = [CoverLetterVerification(has_unsupported_claims=True, unsupported_claims=["invented skill"])]
    monkeypatch.setattr(agent_nodes, "get_chat_model", lambda: _make_scripted_llm(letters, verdicts, counters))

    final = run_pipeline(
        resume_text="Built APIs.",
        jd_text="Must have an invented skill.",
        job_title="Engineer",
        company="Acme Corp",
    )

    # The writer ran at most MAX_COVER_LETTER_ATTEMPTS times -> the loop is finite.
    assert counters["draft"] == agent_nodes.MAX_COVER_LETTER_ATTEMPTS
    assert final["cover_letter_attempts"] == agent_nodes.MAX_COVER_LETTER_ATTEMPTS
    # Despite the unresolved flag, the pipeline still completed end-to-end.
    assert len(final["interview_qa"]["questions"]) == 10
