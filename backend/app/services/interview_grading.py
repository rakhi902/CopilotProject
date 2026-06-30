"""Voice mock-interview grader.

A standalone LLM pass that grades a candidate's (speech-transcribed) interview
answer against the ideal sample answer and returns constructive feedback.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas import InterviewGrade
from app.services.agents.llm_provider import get_chat_model

logger = logging.getLogger("job_copilot")

_MAX_CHARS = 6000

_GRADE_SYSTEM_PROMPT = """You are an experienced, encouraging interview coach grading a
candidate's SPOKEN answer. The answer was auto-transcribed from speech, so ignore minor
transcription glitches, filler words, and punctuation.

You are given the interview QUESTION, an IDEAL sample answer, and the CANDIDATE's actual
answer. Grade the candidate's answer on substance, relevance, structure, and specificity.

Return:
- score: an integer 0-100.
- assessment: a short, encouraging one-paragraph overall judgement.
- strengths: 1-3 concrete things the candidate did well.
- improvements: 1-3 concrete, actionable suggestions (reference the ideal answer where useful).

Be constructive and specific. Never penalize obvious transcription artifacts."""


def grade_answer(question: str, sample_answer: str, user_answer: str) -> InterviewGrade:
    """Grade a transcribed spoken answer against the ideal answer.

    Takes the question that was asked, the grounded sample answer to compare
    against, and the candidate's transcribed answer. Returns an
    :class:`InterviewGrade` with a clamped score and structured feedback.
    """
    model = get_chat_model().with_structured_output(InterviewGrade)
    human_prompt = (
        f"QUESTION:\n{(question or '')[:_MAX_CHARS]}\n\n"
        f"IDEAL SAMPLE ANSWER:\n{(sample_answer or '')[:_MAX_CHARS]}\n\n"
        f"CANDIDATE'S SPOKEN ANSWER (transcribed):\n{(user_answer or '')[:_MAX_CHARS]}"
    )
    result = model.invoke([SystemMessage(content=_GRADE_SYSTEM_PROMPT), HumanMessage(content=human_prompt)])

    return InterviewGrade(
        score=max(0, min(100, int(result.score))),
        assessment=result.assessment or "",
        strengths=[str(s) for s in (result.strengths or [])][:3],
        improvements=[str(s) for s in (result.improvements or [])][:3],
    )
