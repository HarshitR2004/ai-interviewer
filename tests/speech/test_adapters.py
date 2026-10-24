import httpx
import pytest
from test_integration import wav_bytes

from backend.features.live_interviews.models import EngineError
from backend.features.live_interviews.speech import SpeechClient


async def test_independent_services_auth_paths_and_wav():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "stt.example":
            assert request.url.path == "/api/transcribe"
            assert request.headers["authorization"] == "Bearer stt-key"
            assert b'name="audio"' in request.content
            return httpx.Response(200, json={"text": " Answer ", "private_metadata": "discard"})
        assert request.url.host == "tts.example"
        assert request.url.path == "/v2/synthesize"
        assert request.headers["authorization"] == "Bearer tts-key"
        assert b'"text":"Question"' in request.content
        return httpx.Response(200, content=wav_bytes())

    speech = SpeechClient(
        "https://stt.example/api",
        "https://tts.example/v2/",
        stt_api_key="stt-key",
        tts_api_key="tts-key",
        transport=httpx.MockTransport(handler),
    )
    assert await speech.transcribe(wav_bytes()) == {"text": "Answer"}
    assert await speech.synthesize("Question") == wav_bytes()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body,status",
    [
        ({"text": ""}, 422),
        ({"text": None}, 503),
        ({"text": 12}, 503),
        ({}, 503),
        ([], 503),
        ({"text": "x" * 16001}, 422),
    ],
)
async def test_invalid_transcripts(body, status):
    speech = SpeechClient(
        stt_base_url="https://stt.example",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    with pytest.raises(EngineError) as error:
        await speech.transcribe(wav_bytes())
    assert error.value.status == status


async def test_bad_json_and_audio():
    speech = SpeechClient(
        "http://stt.example",
        "http://tts.example",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"invalid")),
    )
    with pytest.raises(EngineError, match="invalid transcript"):
        await speech.transcribe(wav_bytes())
    with pytest.raises(EngineError, match="invalid WAV"):
        await speech.synthesize("Question")
    with pytest.raises(EngineError) as error:
        await speech.transcribe(b"invalid")
    assert error.value.status == 422
    with pytest.raises(EngineError):
        await speech.transcribe(wav_bytes()[:-10])


async def test_absent_capabilities():
    with pytest.raises(EngineError, match="not configured"):
        await SpeechClient(stt_base_url="http://stt.example").synthesize("Question")
    with pytest.raises(EngineError, match="not configured"):
        await SpeechClient(tts_base_url="http://tts.example").transcribe(wav_bytes())


@pytest.mark.parametrize("status", [401, 422, 500])
async def test_provider_errors_are_redacted(status):
    speech = SpeechClient(
        tts_base_url="https://tts.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret-provider-key")
        ),
    )
    with pytest.raises(EngineError) as error:
        await speech.synthesize("Question")
    assert error.value.status == (422 if status == 422 else 503)
    assert "secret-provider-key" not in str(error.value)


async def test_speech_timeout_and_no_auth():
    def handler(request):
        assert "authorization" not in request.headers
        assert request.extensions["timeout"]["read"] == 2
        raise httpx.ReadTimeout("private-timeout", request=request)

    speech = SpeechClient(
        tts_base_url="https://tts.example", timeout=2, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EngineError, match="temporarily unavailable"):
        await speech.synthesize("Question")
