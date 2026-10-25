"""Compare accessible Gemini live models on synthetic interview behavior."""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.integrations.llm.client import ChatCompletionsClient
from backend.modules.live_interviews.reasoning import ModelReasoner
from backend.modules.live_interviews.transitions import new_session
from backend.settings import Settings
from tests.factories import preparation

CASES = [
    ("complete", "Use a transaction and unique database constraint; catch conflicts and return 409."),
    ("incomplete", "I would check first."),
    ("incorrect", "A global boolean in the browser guarantees no duplicates across all users."),
    ("unknown", "I don't know how to solve this."),
    ("clarify", "Can you clarify the question?"),
    ("repeat", "Repeat the question."),
    ("stop", "Stop the interview."),
    ("introduction", "I built a Python booking API for coursework."),
    ("closing", "No further questions, thank you."),
    ("employer", "What is the company's paid leave policy?"),
]


async def main():
    settings = Settings()
    results = []
    for model in ["gemini-3.5-flash-lite", settings.llm_model]:
        client = ChatCompletionsClient(settings.llm_base_url, model, settings.llm_api_key,
                                       reasoning_effort="minimal" if "flash-lite" in model else "low")
        try:
            for name, answer in CASES:
                state = new_session("benchmark", preparation(), time.time(), "prompt")
                state.deadline_at = time.time() + 900
                if name in {"introduction", "closing", "employer"}:
                    state.section.kind = "introduction" if name == "introduction" else "closing"
                    state.current_prompt.text = ("Tell me about yourself." if name == "introduction"
                                                 else "Do you have any questions about the role?")
                if name in {"introduction", "closing", "employer"}:
                    state.question.question = state.current_prompt.text
                started = time.monotonic()
                row = {"model": model, "case": name}
                try:
                    decision = await asyncio.wait_for(ModelReasoner(client).assess(state, answer, 900), 8)
                    expected = {"repeat": "repeat", "stop": "stop", "clarify": "clarification",
                                "employer": "clarification"}.get(name, "answer")
                    passed = decision.intent == expected
                    if name in {"introduction", "closing"}:
                        passed = passed and decision.action == "advance" and not decision.evidence
                    if name == "unknown":
                        passed = passed and decision.action == "advance"
                    row.update(passed=passed, decision=decision.model_dump())
                except Exception as exc:
                    row.update(passed=False, error=type(exc).__name__)
                row["seconds"] = round(time.monotonic() - started, 3)
                results.append(row)
                print(model, name, row["passed"], row["seconds"], flush=True)
        finally:
            await client.aclose()
    summary = []
    for model in dict.fromkeys(r["model"] for r in results):
        rows = [r for r in results if r["model"] == model]
        summary.append({"model": model, "passed": sum(r["passed"] for r in rows),
                        "median_seconds": statistics.median(r["seconds"] for r in rows)})
    Path("work/assessment-benchmark.json").write_text(json.dumps(
        {"summary": summary, "cases": results}, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
