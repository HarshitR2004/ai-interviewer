import asyncio

import pytest

from backend.common.errors import Conflict, InvalidInput
from backend.modules.live_interviews.analysis import InterviewAnalysis
from tests.factories import preparation
from tests.unit.live_interviews.test_service import body, engine


class Generator:
    def __init__(self):
        self.calls = []
        self.instructions = []

    async def generate(self, instruction, content, schema):
        self.calls.append(content)
        self.instructions.append(instruction)
        await asyncio.sleep(0)
        return InterviewAnalysis(
            summary="The candidate described a concurrency strategy.",
            interview_flow=["The candidate answered the opening question."],
            strengths=["The candidate identified a unique constraint."],
            improvements=["Retry handling was not established."],
            next_steps=["Validate retry handling with a transaction work sample."],
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


@pytest.mark.parametrize("persisted", [False, True])
async def test_recruiter_analysis_receives_role_context(tmp_path, persisted):
    from backend.modules.live_interviews.storage import JsonHistoryStore

    store = JsonHistoryStore(tmp_path) if persisted else None
    live, state, _ = await engine(history=store)
    await live.answer_from_transcript(state.session_id, body(state))
    live.end(state.session_id)
    generator = Generator()
    live._analysis_generator = generator
    await live.analyze(state.session_id)
    context = generator.calls[0]["role_context"]
    assert context["job_description"] == preparation().job_description
    assert context["seniority"] == preparation().settings.seniority
    assert "recruiter-facing" in generator.instructions[0]
