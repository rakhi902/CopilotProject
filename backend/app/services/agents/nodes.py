"""The agent nodes that make up the LangGraph pipeline.

Each node is a plain function: it takes the current ``PipelineState`` and returns
a partial state update. Every agent node is wrapped in try/except so a single LLM
failure degrades gracefully: it records an error and returns an empty result
instead of bringing down the whole pipeline. Downstream agents then just work with
whatever context happens to be available.
"""

import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas import CoverLetterVerification, FitAnalysis, InterviewPrep, ResumeRewrite
from app.services.agents.llm_provider import get_chat_model
from app.services.agents.prompts import (
    COVER_LETTER_SYSTEM_PROMPT,
    COVER_LETTER_VERIFIER_SYSTEM_PROMPT,
    FIT_ANALYST_SYSTEM_PROMPT,
    INTERVIEWER_SYSTEM_PROMPT,
    RESUME_WRITER_SYSTEM_PROMPT,
)
from app.services.agents.state import PipelineState

logger = logging.getLogger("job_copilot")

# Caps so an enormous resume or JD can't blow the context window (or the bill).
_MAX_RESUME_CHARS = 16000
_MAX_JD_CHARS = 8000

# The most times the Cover Letter agent may draft the letter (the first draft plus
# any verifier-driven rewrites). This hard cap is what guarantees the
# verify/rewrite loop always terminates, no matter how stubbornly the LLM keeps
# inventing things.
MAX_COVER_LETTER_ATTEMPTS = 2


def _to_dict(structured_result: Any) -> Dict[str, Any]:
    """Turn a Pydantic structured-output result into a plain dict for storage."""
    if hasattr(structured_result, "model_dump"):
        return structured_result.model_dump()
    return dict(structured_result)


def _format_list(items: Optional[List[str]]) -> str:
    """Render a list of strings as a readable bullet block for a prompt.

    Returns a newline-joined bullet list, or a clear placeholder when empty.
    """
    if not items:
        return "(none provided)"
    return "\n".join(f"- {item}" for item in items)


def coordinator_node(state: PipelineState) -> Dict[str, Any]:
    """The graph's entry node: validate and normalize the inputs.

    This is the supervisor. It trims the resume and JD to a safe size so every
    downstream agent works from bounded, clean input.
    """
    resume_text = (state.get("resume_text") or "").strip()
    jd_text = (state.get("jd_text") or "").strip()
    return {
        "resume_text": resume_text[:_MAX_RESUME_CHARS],
        "jd_text": jd_text[:_MAX_JD_CHARS],
    }


def fit_analyst_node(state: PipelineState) -> Dict[str, Any]:
    """Agent 1: compare the resume to the JD and produce a structured fit analysis."""
    try:
        model = get_chat_model().with_structured_output(FitAnalysis)
        human_prompt = (
            f"JOB TITLE: {state['job_title']}\n"
            f"COMPANY: {state['company']}\n\n"
            f"JOB DESCRIPTION:\n{state['jd_text']}\n\n"
            f"CANDIDATE RESUME:\n{state['resume_text']}"
        )
        result = model.invoke(
            [SystemMessage(content=FIT_ANALYST_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]
        )
        return {"fit_analysis": _to_dict(result)}
    except Exception as exc:  # noqa: BLE001 - degrade gracefully instead of crashing the graph
        logger.exception("Fit Analyst agent failed")
        return {"fit_analysis": None, "errors": [f"Fit Analyst failed: {exc}"]}


def resume_writer_node(state: PipelineState) -> Dict[str, Any]:
    """Agent 2: rewrite resume bullets to line up with the JD (parallel branch)."""
    try:
        fit = state.get("fit_analysis") or {}
        model = get_chat_model().with_structured_output(ResumeRewrite)
        human_prompt = (
            f"JOB TITLE: {state['job_title']} at {state['company']}\n\n"
            f"JOB DESCRIPTION:\n{state['jd_text']}\n\n"
            f"FIT ANALYSIS -- emphasize these strengths:\n{_format_list(fit.get('points_to_emphasize'))}\n\n"
            f"FIT ANALYSIS -- address these gaps where the resume honestly supports it:\n"
            f"{_format_list(fit.get('missing_requirements'))}\n\n"
            f"CANDIDATE RESUME (rewrite its bullet points):\n{state['resume_text']}"
        )
        result = model.invoke(
            [SystemMessage(content=RESUME_WRITER_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]
        )
        return {"resume_rewrite": _to_dict(result)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resume Writer agent failed")
        return {"resume_rewrite": None, "errors": [f"Resume Writer failed: {exc}"]}


def cover_letter_node(state: PipelineState) -> Dict[str, Any]:
    """Agent 3: draft a one-page cover letter (runs in parallel with Agent 2).

    Runs once on the way out of the Fit Analyst, and again each time the Governor
    (``verify_cover_letter_node``) sends it back to fix invented claims. On a retry
    the specific unsupported claims the verifier found are fed back in, so this
    rewrite strips them and pivots honestly instead (Rule 3). Every call bumps
    ``cover_letter_attempts`` so the Governor can cap the loop.
    """
    # Count this attempt up front so the tally is right even if drafting fails.
    attempt_number = state.get("cover_letter_attempts", 0) + 1
    try:
        fit = state.get("fit_analysis") or {}
        model = get_chat_model()
        human_prompt = (
            f"JOB TITLE: {state['job_title']}\n"
            f"COMPANY: {state['company']}\n\n"
            f"JOB DESCRIPTION:\n{state['jd_text']}\n\n"
            f"STRENGTHS TO EMPHASIZE:\n{_format_list(fit.get('points_to_emphasize'))}\n\n"
            f"CANDIDATE RESUME:\n{state['resume_text']}"
        )

        # If a previous draft was flagged by the verifier, this is a corrective
        # rewrite: tell the agent exactly which unsupported claims to remove.
        prior_hallucinations = state.get("cover_letter_hallucinations") or []
        if prior_hallucinations:
            human_prompt += (
                "\n\nCORRECTION REQUIRED -- a previous draft made the following claims that are "
                "NOT supported by the resume. Rewrite the letter and REMOVE or honestly rephrase "
                "each one. Where the skill is genuinely required by the JD, apply RULE 3 (the "
                "technical pivot) instead of asserting an unproven skill:\n"
                f"{_format_list(prior_hallucinations)}"
            )

        response = model.invoke(
            [SystemMessage(content=COVER_LETTER_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]
        )
        # A structured model returns an object; a plain chat model returns a message.
        letter_text = getattr(response, "content", None) or str(response)
        return {"cover_letter": letter_text.strip(), "cover_letter_attempts": attempt_number}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cover Letter agent failed")
        return {
            "cover_letter": None,
            "cover_letter_attempts": attempt_number,
            "errors": [f"Cover Letter failed: {exc}"],
        }


def verify_cover_letter_node(state: PipelineState) -> Dict[str, Any]:
    """The Governor: fact-check the latest cover-letter draft against the resume.

    Asks the LLM one question, "does this letter claim any skill or experience not
    present in the resume?", and writes the list of unsupported claims to state.
    ``route_after_cover_letter_verification`` then uses that list (with the attempt
    count) to decide whether to loop back to Agent 3 for a rewrite or move on.

    It always fails open: if there's no letter to check (Agent 3 failed upstream)
    or the verification call itself errors, it reports no problems so the pipeline
    proceeds rather than looping or crashing.
    """
    letter = state.get("cover_letter")
    if not letter:
        # Nothing to verify: the draft failed upstream. Don't trigger a retry.
        return {"cover_letter_hallucinations": []}
    try:
        model = get_chat_model().with_structured_output(CoverLetterVerification)
        human_prompt = (
            f"JOB DESCRIPTION:\n{state['jd_text']}\n\n"
            f"CANDIDATE RESUME (the ONLY source of truth):\n{state['resume_text']}\n\n"
            f"DRAFT COVER LETTER TO AUDIT:\n{letter}"
        )
        verdict = model.invoke(
            [SystemMessage(content=COVER_LETTER_VERIFIER_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]
        )
        hallucinations = list(verdict.unsupported_claims) if verdict.has_unsupported_claims else []
        if hallucinations:
            logger.info("Cover Letter verifier flagged %d unsupported claim(s)", len(hallucinations))
        return {"cover_letter_hallucinations": hallucinations}
    except Exception as exc:  # noqa: BLE001 - fail open: never block the pipeline on the verifier
        logger.exception("Cover Letter verifier failed")
        return {"cover_letter_hallucinations": [], "errors": [f"Cover Letter verifier failed: {exc}"]}


def route_after_cover_letter_verification(state: PipelineState) -> str:
    """Decide whether to rewrite the cover letter or move on to the Interviewer.

    Loops back to Agent 3 only while there are flagged claims and the attempt cap
    hasn't been reached. Once either condition fails it proceeds, which is what
    guarantees the loop always stops within ``MAX_COVER_LETTER_ATTEMPTS`` drafts,
    even if the LLM never stops inventing things.

    Returns ``"retry"`` to send the letter back for a corrective rewrite, or
    ``"proceed"`` to continue.
    """
    hallucinations = state.get("cover_letter_hallucinations") or []
    attempts = state.get("cover_letter_attempts", 0)
    if hallucinations and attempts < MAX_COVER_LETTER_ATTEMPTS:
        return "retry"
    return "proceed"


def interviewer_node(state: PipelineState) -> Dict[str, Any]:
    """Agent 4: generate 10 interview Q&A grounded in the resume.

    Uses the resume, the JD, and the fit analysis as context.
    """
    try:
        fit = state.get("fit_analysis") or {}
        model = get_chat_model().with_structured_output(InterviewPrep)
        human_prompt = (
            f"JOB TITLE: {state['job_title']} at {state['company']}\n\n"
            f"JOB DESCRIPTION:\n{state['jd_text']}\n\n"
            f"OVERALL FIT SUMMARY:\n{fit.get('overall_summary') or '(none)'}\n\n"
            f"CANDIDATE RESUME:\n{state['resume_text']}"
        )
        result = model.invoke(
            [SystemMessage(content=INTERVIEWER_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]
        )
        return {"interview_qa": _to_dict(result)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Interviewer agent failed")
        return {"interview_qa": None, "errors": [f"Interviewer failed: {exc}"]}
