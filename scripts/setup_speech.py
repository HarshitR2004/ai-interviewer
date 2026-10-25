"""Hosted Gemini speech preflight. No downloads or microphone use."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.integrations.voice.speech import GeminiSpeech
from backend.settings import Settings


async def main():
    speech = GeminiSpeech(Settings())
    try:
        total = 0
        async for chunk in speech.audio("Ready for your interview."):
            total += len(chunk)
        if not total:
            raise RuntimeError("Gemini returned no streaming audio.")
        async with speech.client.aio.live.connect(
            model=speech.stt_model,
            config={"response_modalities": ["TEXT"], "input_audio_transcription": {}},
        ):
            print(f"Gemini STT connected; TTS streamed {total} PCM bytes. No local models.")
    finally:
        await speech.close()


if __name__ == "__main__":
    asyncio.run(main())
