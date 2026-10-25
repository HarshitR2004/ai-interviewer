"""Check the configured LLM on synthetic interview input; prints no credentials."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.integrations.llm.client import ChatCompletionsClient
from backend.modules.live_interviews.reasoning import ModelReasoner
from backend.modules.live_interviews.transitions import new_session
from backend.settings import Settings
from tests.factories import preparation


async def main() -> None:
    settings = Settings.model_validate({})
    client = ChatCompletionsClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key)

    async def diagnostics(response):
        await response.aread()
        body = response.json()
        print("provider_status", response.status_code, flush=True)
        for choice in body.get("choices", []):
            print(
                "finish_reason",
                choice.get("finish_reason"),
                "response_characters",
                len(choice.get("message", {}).get("content") or ""),
                flush=True,
            )

    client._client.event_hooks = {"response": [diagnostics]}
    try:
        state = new_session("synthetic", preparation(), 0, "prompt")
        state.deadline_at = 900
        decision = await asyncio.wait_for(
            ModelReasoner(client).assess(
                state,
                "I would use a database transaction and a unique constraint to prevent duplicate bookings.",
                900,
            ),
            12,
        )
        print("assessment_passed", decision.action, flush=True)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
