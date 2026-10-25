import asyncio
import json
from datetime import timedelta

from backend.common.errors import Unavailable
from backend.settings import Settings


class VoiceRooms:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._rooms: set[str] = set()
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str) -> dict[str, str]:
        from livekit import api

        cfg = self.settings
        room = "interview-" + session_id
        async with self._lock:
            if room in self._rooms:
                # Dispatch before a worker registered can leave an empty assignment.
                # Retrying Join must recover it without spawning a second running agent.
                try:
                    async with api.LiveKitAPI(
                        cfg.livekit_url,
                        cfg.livekit_api_key,
                        cfg.livekit_api_secret.get_secret_value(),
                    ) as client:
                        dispatches = await client.agent_dispatch.list_dispatch(room)
                        if not dispatches or not any(d.state.jobs for d in dispatches):
                            for dispatch in dispatches:
                                await client.agent_dispatch.delete_dispatch(dispatch.id, room)
                            self._rooms.discard(room)
                except Exception as exc:
                    raise Unavailable(
                        "LiveKit disconnected. Restart the local server and reconnect."
                    ) from exc
            if room not in self._rooms:
                try:
                    async with api.LiveKitAPI(
                        cfg.livekit_url,
                        cfg.livekit_api_key,
                        cfg.livekit_api_secret.get_secret_value(),
                    ) as client:
                        await client.room.create_room(
                            api.CreateRoomRequest(name=room, max_participants=2)
                        )
                        await client.agent_dispatch.create_dispatch(
                            api.CreateAgentDispatchRequest(
                                agent_name="interviewer",
                                room=room,
                                metadata=json.dumps({"session_id": session_id}),
                            )
                        )
                    self._rooms.add(room)
                except Exception as exc:
                    raise Unavailable(
                        "LiveKit is unavailable. Start the local server and agent worker, then retry."
                    ) from exc
        token = (
            api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret.get_secret_value())
            .with_identity("candidate-" + session_id)
            .with_ttl(timedelta(minutes=10))
            .with_grants(
                api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
            )
        )
        return {"url": cfg.livekit_url, "token": token.to_jwt(), "room": room}

    async def release(self, session_id: str) -> None:
        from livekit import api

        room = "interview-" + session_id
        if room not in self._rooms:
            return
        cfg = self.settings
        try:
            async with api.LiveKitAPI(
                cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret.get_secret_value()
            ) as client:
                await client.room.delete_room(api.DeleteRoomRequest(room=room))
        except Exception:
            return  # Retain for the next cleanup attempt.
        self._rooms.discard(room)

    async def aclose(self) -> None:
        for room in list(self._rooms):
            await self.release(room.removeprefix("interview-"))
