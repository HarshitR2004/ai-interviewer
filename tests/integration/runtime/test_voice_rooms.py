import json
from types import SimpleNamespace

import pytest
from livekit import api

from backend.common.errors import Unavailable
from backend.integrations.voice.rooms import VoiceRooms
from backend.settings import Settings


def config():
    return Settings(_env_file=None, llm_base_url="http://llm.example/v1", llm_model="test")


async def test_room_tokens_dispatch_reuse_and_cleanup(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *args):
            self.room = self
            self.agent_dispatch = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create_room(self, req):
            calls.append(("room", req))

        async def create_dispatch(self, req):
            calls.append(("dispatch", req))

        async def list_dispatch(self, room):
            return [SimpleNamespace(state=SimpleNamespace(jobs=["running"]))]

        async def delete_room(self, req):
            calls.append(("delete", req))

    monkeypatch.setattr(api, "LiveKitAPI", Client)
    rooms = VoiceRooms(config())
    first = await rooms.connect("abc")
    second = await rooms.connect("abc")
    assert first["room"] == second["room"] == "interview-abc"
    token = api.TokenVerifier("devkey", "secret").verify(first["token"])
    assert token.identity == "candidate-abc"
    assert token.video.room == "interview-abc"
    assert len([x for x in calls if x[0] == "dispatch"]) == 1
    assert json.loads(calls[1][1].metadata) == {"session_id": "abc"}
    await rooms.release("abc")
    await rooms.release("abc")
    assert len([x for x in calls if x[0] == "delete"]) == 1


async def test_unavailable_livekit_is_recoverable(monkeypatch):
    def unavailable(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(api, "LiveKitAPI", unavailable)
    with pytest.raises(Unavailable, match="Start the local server"):
        await VoiceRooms(config()).connect("abc")


async def test_join_retry_redispatches_only_when_no_agent_was_assigned(monkeypatch):
    dispatches = []
    deleted = []

    class Client:
        def __init__(self, *args):
            self.room = self
            self.agent_dispatch = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create_room(self, req):
            pass

        async def create_dispatch(self, req):
            dispatches.append(req)

        async def list_dispatch(self, room):
            return [SimpleNamespace(id="empty", state=SimpleNamespace(jobs=[]))]

        async def delete_dispatch(self, dispatch_id, room):
            deleted.append(dispatch_id)

    monkeypatch.setattr(api, "LiveKitAPI", Client)
    rooms = VoiceRooms(config())
    await rooms.connect("abc")
    await rooms.connect("abc")
    assert len(dispatches) == 2 and deleted == ["empty"]
