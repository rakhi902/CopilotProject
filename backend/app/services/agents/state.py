"""The shared state passed between nodes of the LangGraph pipeline."""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict):
    """The one state object every node reads from and writes to.

    LangGraph threads one of these dicts through the graph. Each node returns a
    partial dict, which LangGraph merges in. Most keys use "last value wins", but
    ``errors`` uses an additive reducer (``operator.add``) so the two parallel
    agents (Resume Writer and Cover Letter) can both append to it without
    clobbering each other.
    """

    # Inputs, seeded by the orchestrator before the graph runs.
    resume_text: str
    jd_text: str
    job_title: str
    company: str

    # Outputs, each filled in by exactly one agent.
    fit_analysis: Optional[Dict[str, Any]]      # Fit Analyst
    resume_rewrite: Optional[Dict[str, Any]]    # Resume Writer
    cover_letter: Optional[str]                 # Cover Letter
    interview_qa: Optional[Dict[str, Any]]      # Interviewer

    # Cover-letter self-correction ("the Governor").
    # How many times the Cover Letter agent has drafted the letter (initial draft
    # plus retries); the Governor uses it to cap the verify/rewrite loop.
    cover_letter_attempts: int
    # Unsupported claims the verifier flagged on the latest draft. Drives the retry
    # decision and is fed back to the agent so it knows exactly what to strip.
    cover_letter_hallucinations: Optional[List[str]]

    # Any non-fatal agent errors, concatenated together.
    errors: Annotated[List[str], operator.add]
