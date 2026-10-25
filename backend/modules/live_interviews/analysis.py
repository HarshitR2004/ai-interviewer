"""Transcript-grounded feedback using the interview's configured model."""

from pydantic import BaseModel, Field


class InterviewAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    interview_flow: list[str] = Field(min_length=1, max_length=12)
    strengths: list[str] = Field(max_length=8)
    improvements: list[str] = Field(max_length=8)
    next_steps: list[str] = Field(min_length=1, max_length=8)
    limitations: str = Field(min_length=1, max_length=2000)


ANALYSIS_INSTRUCTION = """Review this completed mock interview for the candidate.
Use the ordered transcript as your primary evidence. Describe overall performance and
the actual flow of questions, answers, follow-ups and clarifications in interview_flow.
Give specific strengths and improvements grounded in examples from the candidate's
answers, and actionable next_steps. Do not invent answers, achievements or topics.
Treat questions marked interrupted as potentially only partly heard. Do not treat a
request to repeat, clarify or stop as a substantive answer. Do not infer vocal delivery,
personality or hiring suitability from text. If the session ended early or evidence is
sparse, explicitly explain that in limitations and keep conclusions proportionate.
Write clear, supportive, candid feedback directly to the candidate. No hiring verdict.
"""
