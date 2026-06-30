"""ATS keyword-density scorer.

A standalone LLM pass, separate from the LangGraph pipeline, that judges how well
a rewritten resume would survive an automated keyword screen against the JD.
"""

import logging
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas import ATSScore
from app.services.agents.llm_provider import get_chat_model

logger = logging.getLogger("job_copilot")

_MAX_CHARS = 12000

_ATS_SYSTEM_PROMPT = """You are an Applicant Tracking System (ATS) keyword analyzer. Simulate how an
automated keyword screen would rate a candidate's (rewritten) resume against the target job
description, and explain the result honestly.

METHOD -- work through these steps; do not eyeball a number:
1. Extract the JD's important terms: hard skills, tools, technologies, certifications, and core
   responsibilities. Weight must-have and repeated terms more heavily than nice-to-haves.
2. Decide which of those terms are GENUINELY PRESENT in the resume -- i.e. the resume shows real
   use or experience of them.
3. A term does NOT count when it appears only inside a negative, disclaiming, or purely aspirational
   context -- e.g. "haven't used React", "no CUDA experience", "eager to learn Kubernetes",
   "familiar with but never shipped X". A crude scanner may substring-match these, but they signal a
   gap, not a qualification: treat them as MISSING and never reward self-defeating phrasing.
4. score = the weighted share of the JD's important terms genuinely present, as an integer 0-100,
   with heavier weight on must-have skills. Be consistent -- a resume missing several core terms
   cannot land in the 80s.

FEEDBACK -- return 2-3 SPECIFIC, actionable bullet points:
- Name concrete JD keywords or phrases that are missing or under-represented and should be added,
  ONLY where the candidate could honestly claim them from the resume.
- If a JD keyword shows up only in a negative or aspirational phrase, call it out and tell the
  candidate to either substantiate it with real experience or cut the hedge (it earns nothing and
  reads as a gap).
- Never invent experience and never suggest stuffing a keyword the candidate cannot honestly support.

Base everything strictly on the two texts provided. Be precise and concrete, never generic."""


def score_ats(resume_rewrite: Optional[Dict[str, Any]], jd_text: str) -> ATSScore:
    """Score a rewritten resume against a JD for ATS keyword match.

    ``resume_rewrite`` is the Resume Writer artifact (a dict with a ``bullets``
    list). Returns an :class:`ATSScore` with a clamped 0-100 score and up to three
    feedback bullets.
    """
    bullets = (resume_rewrite or {}).get("bullets") or []
    resume_text = "\n".join("- " + (b.get("rewritten_bullet") or "") for b in bullets)

    model = get_chat_model().with_structured_output(ATSScore)
    human_prompt = (
        f"JOB DESCRIPTION:\n{jd_text[:_MAX_CHARS]}\n\n"
        f"CANDIDATE RESUME (rewritten bullets):\n{resume_text[:_MAX_CHARS]}"
    )
    result = model.invoke([SystemMessage(content=_ATS_SYSTEM_PROMPT), HumanMessage(content=human_prompt)])

    score = max(0, min(100, int(result.score)))
    feedback = [str(item) for item in (result.feedback or [])][:3]
    return ATSScore(score=score, feedback=feedback)
