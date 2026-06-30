"""Schemas for the extra analysis features.

These power four standalone endpoints that sit outside the LangGraph pipeline:
the ATS scorer, the spoken-answer grader, the salary-negotiation coach, and (with
no schema of its own) the calendar export. Each LLM-backed schema is both the
agent's structured-output target and the endpoint's response model.
"""

from typing import List

from pydantic import BaseModel, Field


# 1. ATS keyword-density scorer
class ATSScore(BaseModel):
    """An ATS keyword-match verdict for a rewritten resume against a JD."""

    score: int = Field(description="ATS keyword-match score, 0-100 (higher is better).")
    feedback: List[str] = Field(
        default_factory=list,
        description="2-3 specific, actionable suggestions (concrete missing keywords).",
    )


# 2. Voice mock-interview grader
class InterviewGradeRequest(BaseModel):
    """Body for grading a (voice-transcribed) interview answer."""

    question: str = Field(min_length=1)
    sample_answer: str = Field(default="", description="The ideal answer to compare against.")
    user_answer: str = Field(min_length=1, description="The candidate's transcribed spoken answer.")


class InterviewGrade(BaseModel):
    """The coach's grade for a candidate's spoken answer."""

    score: int = Field(description="Overall answer score, 0-100.")
    assessment: str = Field(default="", description="A short, encouraging overall judgement.")
    strengths: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)


# 3. Salary-negotiation coach
class SalaryCoachRequest(BaseModel):
    """Body for the salary coach: the base salary the candidate was offered."""

    offered_salary: str = Field(min_length=1, description="Offered base salary, as the user typed it.")


class NegotiationScript(BaseModel):
    """A single, ready-to-use negotiation script."""

    title: str
    body: str


class SalaryCoaching(BaseModel):
    """Two distinct negotiation scripts for the offered role."""

    scripts: List[NegotiationScript] = Field(default_factory=list)
