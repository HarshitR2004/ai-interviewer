import asyncio
from types import SimpleNamespace

import pytest
from livekit.agents import llm

from backend.voice_agent import InterviewAgent


class Backend:
    def __init__(self):
        self.base = "/api/live-sessions/test"
        self.started = asyncio.Event()
        self.block = True
        self.inputs = []
        self.committed = None

    async def state(self):
        return {
            "status": "active",
            "current_prompt": {"id": "p", "text": "Question"},
            "last_turn_id": self.committed,
        }

    async def event(self, kind, **kwargs):
        return await self.state()

    async def answer(self, prompt_id, turn_id, text):
        self.inputs.append(text)
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        self.committed = turn_id
        return {"session": await self.state(), "spoken_text": "The next question."}


def context(text):
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content=text)
    return ctx


async def test_continuation_keeps_uncommitted_answer():
    backend = Backend()

    async def publish(*args, **kwargs):
        pass

    agent = InterviewAgent(
        backend,
        SimpleNamespace(
            isconnected=lambda: True, local_participant=SimpleNamespace(publish_data=publish)
        ),
    )
    first = agent.llm_node(context("I use a transaction."), [], None)
    task = asyncio.create_task(anext(first))
    await backend.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    backend.block = False
    second = agent.llm_node(context("And a unique constraint."), [], None)
    assert await anext(second) == "The next question."
    assert backend.inputs[-1] == "I use a transaction. And a unique constraint."
    await second.aclose()


async def test_lost_committed_response_is_not_merged_into_new_answer():
    backend = Backend()
    backend.block = False
    backend.committed = "previous"

    async def publish(*args, **kwargs):
        pass

    agent = InterviewAgent(
        backend,
        SimpleNamespace(
            isconnected=lambda: True, local_participant=SimpleNamespace(publish_data=publish)
        ),
    )
    agent.pending_id = "previous"
    agent.pending_prompt = "p"
    agent.pending_text = "Already saved answer."
    node = agent.llm_node(context("New answer."), [], None)
    await anext(node)
    assert backend.inputs == ["New answer."]
    await node.aclose()
