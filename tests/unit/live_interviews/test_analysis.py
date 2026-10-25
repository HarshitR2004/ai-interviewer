import asyncio

import pytest

from backend.common.errors import Conflict, InvalidInput
from backend.modules.live_interviews.analysis import InterviewAnalysis
from tests.unit.live_interviews.test_service import body, engine


class Generator:
    def __init__(self):
        self.calls = []

    async def generate(self, instruction, content, schema):
        self.calls.append(content)
        await asyncio.sleep(0)
        return InterviewAnalysis(
            summary="You explained a concurrency strategy.",
            interview_flow=["You answered the opening question."],
            strengths=["You mentioned a unique constraint."],
            improvements=["Explain how you handle retries."],
            next_steps=["Practice a concrete transaction example."],
            limitations="The interview ended early, so evidence is limited.",
        )


async def test_analysis_requires_end_and_candidate_answers():
    live, state, _ = await engine()
    with pytest.raises(Conflict):
        await live.analyze(state.session_id)
    live.end(state.session_id)
    with pytest.raises(InvalidInput):
        await live.analyze(state.session_id)


async def test_analysis_uses_saved_transcript_and_deduplicates_requests():
    live, state, _ = await engine()
    await live.answer_from_transcript(state.session_id, body(state))
    live.end(state.session_id)
    generator = Generator()
    live._analysis_generator = generator
    first, second = await asyncio.gather(
        live.analyze(state.session_id), live.analyze(state.session_id)
    )
    assert first == second
    assert len(generator.calls) == 1
    assert generator.calls[0]["transcript"][0]["text"] == body(state).text
    assert generator.calls[0]["session"]["completion_reason"] == "user_ended"
