import io
import wave

from backend.common.errors import InvalidInput

MAX_AUDIO_BYTES = 12 * 1024 * 1024


def validate_wav(content: bytes) -> None:

    # Check audio encoding, duration, and size before accepting WAV data.
    try:
        if not content or len(content) > MAX_AUDIO_BYTES:
            raise ValueError

        with wave.open(io.BytesIO(content), "rb") as audio:
            frames = audio.getnframes()

            channels = audio.getnchannels()

            rate = audio.getframerate()

            if (
                audio.getsampwidth() != 2
                or channels not in {1, 2}
                or not 8000 <= rate <= 48000
                or not 0 < frames <= rate * 120
                or len(audio.readframes(frames)) != frames * channels * 2
            ):
                raise ValueError

    except (wave.Error, EOFError, ValueError, OSError) as exc:
        raise InvalidInput(
            "Use a complete 16-bit PCM WAV, 8–48 kHz, up to 120 seconds and 12 MB."
        ) from exc
