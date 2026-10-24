from backend.modules.pre_interview.interview_planning.models import RoleRequirements
from backend.modules.pre_interview.profiles.models import CandidateProfile


class FakeModel:
    def __init__(self, persona, plan):
        self.persona, self.plan = persona, plan
        self.calls = []
        self.fail_plan = False

    async def generate(self, instruction, content, schema, check=None):
        self.calls.append(schema)
        if schema is CandidateProfile:
            result = self.persona.model_copy(deep=True)
            if check:
                check(result)
            return result
        if self.fail_plan:
            raise RuntimeError("generation failed")
        if schema is RoleRequirements:
            return RoleRequirements(
                role=self.plan.role, competencies=self.plan.required_competencies
            )
        section_type = schema.model_fields["sections"].annotation
        from typing import get_args

        sections = {}
        for index, (key, field) in enumerate(section_type.model_fields.items()):
            section = self.plan.sections[index % len(self.plan.sections)].model_dump()
            section["competency"] = get_args(
                field.annotation.model_fields["competency"].annotation
            )[0]
            sections[key] = section
        result = schema.model_validate({"role": self.plan.role, "sections": sections})
        if check:
            check(result)
        return result


class FakeReasoner:
    def __init__(self, action="advance"):
        self.calls = 0
        self.action = action

    async def assess(self, snapshot, answer, remaining_seconds):
        from backend.modules.live_interviews.models import Decision

        self.calls += 1
        return Decision(action=self.action, next_question="Explain your reasoning more clearly.")


class BlockingReasoner(FakeReasoner):
    def __init__(self):
        import asyncio

        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def assess(self, snapshot, answer, remaining_seconds):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        from backend.modules.live_interviews.models import Decision

        return Decision(action=self.action, next_question="Explain your reasoning more clearly.")


class FakeSpeech:
    def __init__(self):
        self.calls = 0

    async def transcribe(self, content):
        from backend.integrations.speech.contracts import Transcript

        self.calls += 1
        return Transcript(text="Use a unique database constraint and a transaction.")

    async def synthesize(self, text):
        from tests.factories import wav_bytes

        return wav_bytes()


def make_preparation(store, model):
    from backend.modules.pre_interview.interview_planning.service import InterviewService
    from backend.modules.pre_interview.preparation.service import PreparationService
    from backend.modules.pre_interview.profiles.service import ProfileService
    from backend.modules.pre_interview.resume_ingestion.pdf_extractor import PdfExtractor
    from backend.modules.pre_interview.resume_ingestion.service import ResumeIngestionService

    return PreparationService(
        store,
        ProfileService(model),
        InterviewService(model),
        ResumeIngestionService(PdfExtractor()),
    )


class FakePreparation:
    def __init__(self, value):
        self.value = value

    async def get(self, candidate_id):
        return self.value.model_copy(deep=True)
