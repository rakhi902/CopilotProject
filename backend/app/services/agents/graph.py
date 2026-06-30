"""Build, compile, and run the multi-agent LangGraph pipeline.

The topology is a coordinator with a three-way parallel stage::

    START -> coordinator -> fit_analyst -+-> resume_writer ---------------------+-> END
                                         +-> interviewer ----------------------+
                                         \\-> cover_letter_writer -> verify_cover_letter
                                                     ^                      |
                                                     +----- "retry" --------+  ("proceed") -> END

The Fit Analyst (Agent 1) fans out to all three downstream agents (Resume Writer,
Cover Letter, and Interviewer), which run as parallel branches. The Cover Letter
branch also passes through the Governor (``verify_cover_letter``), which checks the
draft against the resume and either loops back for a corrective rewrite ("retry",
capped at ``MAX_COVER_LETTER_ATTEMPTS`` drafts) or proceeds. All three branches
join at END, which LangGraph reaches only once every branch (including any
cover-letter correction loop) has finished.
"""

from functools import lru_cache
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from app.services.agents.nodes import (
    _MAX_JD_CHARS,
    _MAX_RESUME_CHARS,
    coordinator_node,
    cover_letter_node,
    fit_analyst_node,
    interviewer_node,
    resume_writer_node,
    route_after_cover_letter_verification,
    verify_cover_letter_node,
)
from app.services.agents.state import PipelineState


def build_pipeline_graph():
    """Wire the nodes and edges into a compiled, runnable LangGraph."""
    builder = StateGraph(PipelineState)

    # Register every node: the coordinator, the four agents, and the Governor
    # (verify_cover_letter) that fact-checks the cover letter.
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("fit_analyst", fit_analyst_node)
    builder.add_node("resume_writer", resume_writer_node)
    builder.add_node("cover_letter_writer", cover_letter_node)
    builder.add_node("verify_cover_letter", verify_cover_letter_node)
    builder.add_node("interviewer", interviewer_node)

    # Entry: the coordinator prepares the inputs, then Agent 1 analyses fit.
    builder.add_edge(START, "coordinator")
    builder.add_edge("coordinator", "fit_analyst")

    # Fan out: the fit analysis feeds all three downstream agents. Each depends
    # only on that analysis, so edges from fit_analyst to all three let LangGraph
    # schedule them together in the next step.
    builder.add_edge("fit_analyst", "resume_writer")
    builder.add_edge("fit_analyst", "cover_letter_writer")
    builder.add_edge("fit_analyst", "interviewer")

    # Resume Writer and Interviewer flow straight to the join at END.
    builder.add_edge("resume_writer", END)
    builder.add_edge("interviewer", END)

    # The Cover Letter branch passes through the Governor before joining. The
    # verifier's conditional edge either loops back to Agent 3 for a rewrite
    # ("retry") or proceeds to END ("proceed"). The retry path is the
    # self-correction loop; the attempt cap inside the router keeps it finite.
    builder.add_edge("cover_letter_writer", "verify_cover_letter")
    builder.add_conditional_edges(
        "verify_cover_letter",
        route_after_cover_letter_verification,
        {"retry": "cover_letter_writer", "proceed": END},
    )

    # END joins all three parallel branches: LangGraph reaches it only once the
    # Resume, Interview, and fully-settled Cover Letter branches have finished.
    return builder.compile()


@lru_cache(maxsize=1)
def get_compiled_pipeline():
    """Return the process-wide compiled pipeline, building it once on first use.

    Compilation is cached because the graph is stateless between runs (all state
    is passed into ``.invoke``), so one compiled instance is safe to reuse.
    """
    return build_pipeline_graph()


def run_pipeline(resume_text: str, jd_text: str, job_title: str, company: str) -> Dict[str, Any]:
    """Run the full pipeline and return the final merged state.

    This is the orchestrator entry point the background generation task calls. It
    seeds the initial state and invokes the compiled graph. The returned dict
    carries ``fit_analysis``, ``resume_rewrite``, ``cover_letter``, ``interview_qa``,
    and any accumulated ``errors``.
    """
    pipeline = get_compiled_pipeline()
    initial_state: Dict[str, Any] = {
        "resume_text": resume_text or "",
        "jd_text": jd_text or "",
        "job_title": job_title or "",
        "company": company or "",
        "fit_analysis": None,
        "resume_rewrite": None,
        "cover_letter": None,
        "interview_qa": None,
        "cover_letter_attempts": 0,
        "cover_letter_hallucinations": None,
        "errors": [],
    }
    return pipeline.invoke(initial_state)


# Artifacts that can be regenerated one at a time, mapped to (the Draft column /
# state key, the single agent node that produces it). The fit analysis isn't here
# on purpose: it's the shared input to the others, so regenerating it would
# invalidate them.
_SINGLE_AGENT_NODES = {
    "resume": ("resume_rewrite", resume_writer_node),
    "cover": ("cover_letter", cover_letter_node),
    "interview": ("interview_qa", interviewer_node),
}
REGENERATABLE_ARTIFACTS = tuple(_SINGLE_AGENT_NODES.keys())


def run_single_agent(
    artifact: str,
    *,
    resume_text: str,
    jd_text: str,
    job_title: str,
    company: str,
    fit_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Re-run exactly one agent in isolation, for per-artifact regeneration.

    Instead of re-running the whole graph, this seeds a minimal state (the inputs
    plus the existing fit analysis, which the downstream agents consume) and calls
    a single agent node directly. The cover-letter Governor loop is skipped here:
    regeneration re-runs only the one named agent.

    Returns ``{"state_key": <Draft column name>, "value": <artifact or None>,
    "errors": [<any non-fatal agent errors>]}``. Raises ``ValueError`` if the
    artifact isn't regeneratable.
    """
    if artifact not in _SINGLE_AGENT_NODES:
        raise ValueError(
            f"'{artifact}' is not a regeneratable artifact; choose one of {REGENERATABLE_ARTIFACTS}."
        )
    state_key, node = _SINGLE_AGENT_NODES[artifact]
    state: Dict[str, Any] = {
        "resume_text": (resume_text or "").strip()[:_MAX_RESUME_CHARS],
        "jd_text": (jd_text or "").strip()[:_MAX_JD_CHARS],
        "job_title": job_title or "",
        "company": company or "",
        "fit_analysis": fit_analysis,
        "resume_rewrite": None,
        "cover_letter": None,
        "interview_qa": None,
        "cover_letter_attempts": 0,
        "cover_letter_hallucinations": None,
        "errors": [],
    }
    result = node(state)
    errors: List[str] = result.get("errors") or []
    return {"state_key": state_key, "value": result.get(state_key), "errors": errors}
