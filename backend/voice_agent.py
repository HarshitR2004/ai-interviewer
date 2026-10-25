"""Local LiveKit worker: python -m backend.voice_agent dev."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import uuid4

import httpx
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, llm, room_io, tts

from backend.integrations.voice.speech import GeminiSpeech, GeminiSTT, GeminiTTS
from backend.settings import Settings

log = logging.getLogger(__name__)


class Backend:
    def __init__(self, settings: Settings, session_id: str):
        self.base = f"/api/live-sessions/{session_id}"
        self.client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=12,
            headers={"X-Agent-Secret": settings.agent_secret.get_secret_value()},
            trust_env=False,
        )

    async def state(self) -> dict[str, Any]:
        response = await self.client.get(self.base + "/agent")
        response.raise_for_status()
        return dict(response.json())

    async def event(self, kind: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.post(
            self.base + "/agent/events", json={"kind": kind, **kwargs}
        )
        response.raise_for_status()
        return dict(response.json())

    async def answer(self, prompt_id: str, turn_id: str, text: str) -> dict[str, Any]:
        # A lost response can be retried without assessing/advancing the same turn twice.
        for attempt in range(2):
            try:
                response = await self.client.post(
                    self.base + "/agent/turns",
                    json={"prompt_id": prompt_id, "turn_id": turn_id, "text": text},
                )
                response.raise_for_status()
                return dict(response.json())
            except httpx.TransportError:
                if attempt:
                    raise
        raise RuntimeError("Answer request failed")


class WorkflowLLM(llm.LLM[Any]):
    """Marker for LiveKit scheduling; InterviewAgent.llm_node owns inference."""

    def chat(self, **kwargs: Any) -> Any:
        raise RuntimeError("Use the interview workflow node, not a second conversational LLM.")


class InterviewAgent(Agent):
    def __init__(self, backend: Backend, room: rtc.Room):
        super().__init__(instructions="Conduct the prepared English interview.", llm=WorkflowLLM())
        self.backend, self.room = backend, room
        self.state: dict[str, Any] = {}
        self.pending_text = ""
        self.pending_id: str | None = None
        self.pending_prompt: str | None = None
        self.pending_task: asyncio.Task[Any] | None = None
        self.tasks: set[asyncio.Task[Any]] = set()
        self.interrupted = False
        self.spoken_prompt: str | None = None
        self.last_command = 0.0
        self.opening_audio: tts.ChunkedStream | None = None
        self.opening_prompt: str | None = None

    async def prepare_opening(self, provider: GeminiTTS) -> None:
        """Start cloud synthesis while the worker and browser connect."""
        state = await self.backend.state()
        prompt = state.get("current_prompt")
        if prompt and state["status"] not in {"completed", "failed"}:
            self.opening_prompt = prompt["id"]
            self.opening_audio = provider.synthesize(prompt["text"])

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            if not done.cancelled() and done.exception():
                log.error("Voice background operation failed", exc_info=done.exception())

        task.add_done_callback(finished)

    async def publish(self, kind: str, **data: Any) -> None:
        if not self.room.isconnected():
            return
        try:
            await self.room.local_participant.publish_data(
                json.dumps({"kind": kind, **data}), reliable=True
            )
        except Exception:
            if self.room.isconnected():
                raise

    async def on_enter(self) -> None:
        self.state = await self.backend.state()
        prompt = self.state.get("current_prompt")
        if prompt and self.state["status"] == "active":
            self.spoken_prompt = prompt["id"]
            if self.opening_audio and self.opening_prompt == prompt["id"]:
                stream = self.opening_audio

                async def frames() -> Any:
                    try:
                        async for chunk in stream:
                            yield chunk.frame
                    finally:
                        await stream.aclose()

                await self.session.say(prompt["text"], audio=frames())
            else:
                await self.session.say(prompt["text"])

    async def llm_node(self, chat_ctx: llm.ChatContext, tools: Any, model_settings: Any) -> Any:
        messages = [
            item
            for item in chat_ctx.items
            if isinstance(item, llm.ChatMessage) and item.role == "user"
        ]
        text = (messages[-1].text_content or "").strip() if messages else ""
        if not text:
            return
        self.state = await self.backend.state()
        prompt = self.state.get("current_prompt")
        if self.state["status"] != "active" or not prompt:
            return
        if self.state.get("last_turn_id") == self.pending_id or (
            self.pending_prompt and self.pending_prompt != prompt["id"]
        ):
            self.pending_text = ""
        if self.pending_text and not text.startswith(self.pending_text):
            text = self.pending_text + " " + text
        self.pending_text, self.pending_id, self.pending_prompt = text, uuid4().hex, prompt["id"]
        turn_id = self.pending_id
        self.pending_task = asyncio.current_task()
        started = time.perf_counter()
        try:
            result = await self.backend.answer(prompt["id"], turn_id, text)
            self.state = result["session"]
            self.pending_text, self.pending_id = "", None
            await self.publish("session", session=self.state)
            log.info("session=%s turn=%s assessment_seconds=%.3f",
                     self.backend.base, turn_id, time.perf_counter() - started)
            self.spoken_prompt = (self.state.get("current_prompt") or {}).get("id")
            yield result["spoken_text"]
        except asyncio.CancelledError:
            # Invalidation is server-side too; client cancellation alone cannot roll back HTTP work.
            await asyncio.shield(self.backend.event("invalidate"))
            self.state = await asyncio.shield(self.backend.state())
            if self.state.get("last_turn_id") == turn_id:
                self.pending_text, self.pending_id = "", None
            raise
        except (httpx.HTTPError, RuntimeError):
            await self.publish(
                "error", message="I couldn't process that turn. Please repeat your answer."
            )
            yield "I couldn't process that turn. Please repeat your answer."
        finally:
            if self.pending_task is asyncio.current_task():
                self.pending_task = None

    async def control(self, data: rtc.RpcInvocationData) -> str:
        expected = "candidate-" + self.backend.base.rsplit("/", 1)[-1]
        if data.caller_identity != expected:
            raise ValueError("Only this interview's candidate can control it.")
        command = json.loads(data.payload).get("action")
        if time.monotonic() - self.last_command < 0.3:
            return "busy"
        self.last_command = time.monotonic()
        if command in {"repeat", "stop"}:
            await self.session.interrupt(force=True)
            if command == "repeat":
                self.state = await self.backend.state()
                prompt = self.state.get("current_prompt")
                if prompt:
                    self.spawn(self.say_prompt(prompt["text"], prompt["id"]))
        else:
            raise ValueError("Unknown voice command.")
        return "ok"

    async def say_prompt(self, text: str, prompt_id: str | None) -> None:
        self.spoken_prompt = prompt_id
        await self.session.say(text)


def main() -> None:
    settings = Settings.model_validate({})
    server = agents.AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
        num_idle_processes=1,
        initialize_process_timeout=180,
        load_fnc=lambda: 0.0,
    )

    @server.rtc_session(agent_name="interviewer")
    async def entrypoint(ctx: agents.JobContext) -> None:
        metadata = json.loads(ctx.job.metadata)
        session_id = metadata["session_id"]
        backend = await asyncio.to_thread(Backend, settings, session_id)
        agent = InterviewAgent(backend, ctx.room)
        speech = await asyncio.to_thread(GeminiSpeech, settings)
        provider = GeminiTTS(speech)
        session: AgentSession[Any] = AgentSession(
            stt=GeminiSTT(speech),
            tts=provider,
            vad=None,
            turn_handling={
                "turn_detection": "stt",
                "endpointing": {
                    "min_delay": 0,
                    "max_delay": 0,
                },
                "interruption": {
                    "mode": "vad",
                    "enabled": True,
                    "min_duration": settings.interruption_duration,
                    "min_words": 0,
                    "resume_false_interruption": True,
                    "discard_audio_if_uninterruptible": False,
                },
                "preemptive_generation": {"enabled": False},
            },
            user_away_timeout=None,
            aec_warmup_duration=0.5,
        )
        done = asyncio.Event()
        disconnect_task: asyncio.Task[Any] | None = None

        @ctx.room.on("disconnected")
        def room_closed(*args: Any) -> None:
            done.set()

        async def refresh() -> None:
            try:
                while not done.is_set():
                    state = await backend.state()
                    agent.state = state
                    await agent.publish("session", session=state)
                    if state["status"] in {"completed", "failed"}:
                        await asyncio.sleep(4)
                        done.set()
                        break
                    await asyncio.sleep(1)
            except Exception:
                done.set()
                raise

        async def disconnected() -> None:
            await backend.event("disconnected")
            if agent.pending_task:
                agent.pending_task.cancel()
            await session.interrupt(force=True)
            session.clear_user_turn()
            agent.pending_text = ""
            await asyncio.sleep(30)
            done.set()

        @ctx.room.on("participant_disconnected")
        def on_disconnected(participant: rtc.RemoteParticipant) -> None:
            nonlocal disconnect_task
            if participant.identity == "candidate-" + session_id:
                disconnect_task = asyncio.create_task(disconnected())

        @ctx.room.on("participant_connected")
        def on_reconnected(participant: rtc.RemoteParticipant) -> None:
            nonlocal disconnect_task
            if participant.identity == "candidate-" + session_id and disconnect_task:
                disconnect_task.cancel()
                disconnect_task = None

                async def resume() -> None:
                    state = await backend.event("joined")
                    if state["status"] == "active":
                        session.clear_user_turn()
                        agent.pending_text = ""
                        prompt = state.get("current_prompt")
                        if prompt:
                            await agent.say_prompt(prompt["text"], prompt["id"])

                agent.spawn(resume())

        @session.on("user_state_changed")
        def user_state(event: Any) -> None:
            if event.new_state == "speaking":
                if agent.pending_task:
                    agent.pending_task.cancel()

                async def stop_playback() -> None:
                    await session.interrupt(force=True)

                agent.spawn(stop_playback())

        @session.on("agent_state_changed")
        def agent_state(event: Any) -> None:
            agent.spawn(agent.publish("state", state=event.new_state))

        @session.on("user_input_transcribed")
        def transcript(event: Any) -> None:
            agent.spawn(agent.publish("caption", text=event.transcript, final=event.is_final))

        @session.on("conversation_item_added")
        def conversation(event: Any) -> None:
            if isinstance(event.item, llm.ChatMessage) and event.item.role == "assistant":
                agent.spawn(
                    backend.event(
                        "playback",
                        text=event.item.text_content or "",
                        prompt_id=agent.spoken_prompt,
                        interrupted=event.item.interrupted,
                    )
                )

        @session.on("error")
        def error(event: Any) -> None:
            if getattr(event.error, "type", "") == "stt_error":
                if agent.pending_task:
                    agent.pending_task.cancel()
                session.clear_user_turn()
                agent.pending_text = ""
            agent.spawn(
                agent.publish(
                    "error", message="Gemini speech failed. Repeat the question, or reconnect and repeat your answer."
                )
            )

        @session.on("metrics_collected")
        def metrics(event: Any) -> None:
            metric = event.metrics
            if hasattr(metric, "ttfb"):
                log.info("tts_first_chunk_seconds=%.3f", metric.ttfb)
            if hasattr(metric, "end_of_utterance_delay"):
                log.info("endpoint_seconds=%.3f", metric.end_of_utterance_delay)

        try:
            async with asyncio.TaskGroup() as startup:
                startup.create_task(ctx.connect())
                startup.create_task(agent.prepare_opening(provider))
            await backend.event("ready")
            await ctx.wait_for_participant(identity="candidate-" + session_id)
            agent.state = await backend.event("joined")
            ctx.room.local_participant.register_rpc_method("control", agent.control)
            await session.start(
                agent=agent,
                room=ctx.room,
                record=False,
                room_options=room_io.RoomOptions(text_input=False, close_on_disconnect=False),
            )
            agent.spawn(refresh())
            await done.wait()
        except Exception:
            log.exception("Voice interview failed")
            await backend.event("failed")
            raise
        finally:
            if disconnect_task:
                disconnect_task.cancel()
            for task in agent.tasks:
                task.cancel()
            await asyncio.gather(*agent.tasks, return_exceptions=True)
            await session.aclose()
            if agent.opening_audio:
                await agent.opening_audio.aclose()
            await speech.close()
            await backend.client.aclose()

    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
