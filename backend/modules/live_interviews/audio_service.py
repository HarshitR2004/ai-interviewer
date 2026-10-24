from backend.common.errors import InvalidInput, Unavailable
from backend.integrations.speech.contracts import Synthesizer, Transcriber

from .models import AnswerInput, AnswerResult
from .service import LiveInterviewService


class AudioInterviewService:
    def __init__(
        self,
        live: LiveInterviewService,
        transcriber: Transcriber | None,
        synthesizer: Synthesizer | None,
    ):
        self._live, self._transcriber, self._synthesizer = live, transcriber, synthesizer

    async def answer(self, session_id: str, content: bytes, prompt_id: str) -> AnswerResult:
        # Hold one session guard across transcription and assessment to prevent competing answers.
        with self._live.operation(session_id) as state:
            self._live.require_prompt(state, prompt_id)
            if self._transcriber is None:
                raise Unavailable("Speech transcription is disabled.")
            self._live.require_reasoning()
            if len(content) > 12 * 1024 * 1024:
                raise InvalidInput("Recording must be smaller than 12 MB.")
            transcript = await self._transcriber.transcribe(content)
            body = AnswerInput(prompt_id=prompt_id, answer=transcript.text)
            result = await self._live.assess_answer(state, body)
            return result.model_copy(update={"transcription": transcript})

    async def prompt_audio(self, session_id: str, prompt_id: str) -> bytes:
        # Recheck the prompt after synthesis so expired audio is not returned.
        with self._live.operation(session_id) as state:
            self._live.require_prompt(state, prompt_id)
            if self._synthesizer is None:
                raise Unavailable("Speech synthesis is disabled.")
            assert state.current_prompt is not None
            audio = await self._synthesizer.synthesize(state.current_prompt.text)
            self._live.require_prompt(state, prompt_id)
            return audio
