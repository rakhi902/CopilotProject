"""Salary-negotiation coach.

A standalone LLM pass that turns a role plus an offered base salary into two
distinct, ready-to-use negotiation scripts.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas import NegotiationScript, SalaryCoaching
from app.services.agents.llm_provider import get_chat_model

logger = logging.getLogger("job_copilot")

_SALARY_SYSTEM_PROMPT = """You are an expert salary-negotiation coach. Given a role, a company,
and an offered base salary, write TWO distinct, ready-to-use negotiation scripts the candidate
can adapt and send (or say).

Produce EXACTLY two scripts:
1. "Aggressive / Market-Rate" -- confidently anchors to market data and pushes for a higher base.
2. "Value-Based / Equity-Focused" -- emphasizes the candidate's value and explores total
   compensation (equity, bonus, signing, benefits) rather than base salary alone.

For each script return a short title and a body: a concise, polite, professional message of
roughly 4-8 sentences. Do NOT invent precise market figures you cannot justify -- speak in
ranges and principles. Keep the tone collaborative, never entitled.

CURRENCY: All compensation is in Indian Rupees (INR, ₹). Reference every amount in rupees using
Indian conventions (lakhs / LPA where natural); never use $ or any non-INR currency."""


def coach_salary(job_title: str, company: str, offered_salary: str) -> SalaryCoaching:
    """Generate two negotiation scripts for an offer.

    Takes the job title, the hiring company, and the offered base salary as the
    user entered it. Returns a :class:`SalaryCoaching` with up to two scripts.
    """
    model = get_chat_model().with_structured_output(SalaryCoaching)
    human_prompt = (
        f"JOB TITLE: {job_title}\n"
        f"COMPANY: {company}\n"
        f"OFFERED BASE SALARY (INR ₹): {offered_salary}"
    )
    result = model.invoke([SystemMessage(content=_SALARY_SYSTEM_PROMPT), HumanMessage(content=human_prompt)])

    scripts = [
        NegotiationScript(title=script.title, body=script.body)
        for script in (result.scripts or [])
    ][:4]
    return SalaryCoaching(scripts=scripts)
