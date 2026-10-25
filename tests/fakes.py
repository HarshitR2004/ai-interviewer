from backend.modules.pre_interview.preparation.models import RoleRequirements
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
            kind = get_args(field.annotation.model_fields["kind"].annotation)[0]
            section["kind"] = kind
            section["covered_competencies"] = (
                self.plan.required_competencies if kind not in {"introduction", "closing"} else []
            )
            question = section["questions"][0]
            question["question"] = f"Tell me about {kind.replace('_', ' ')} topic {index + 1}."
            if kind not in {"project_overview", "project_detail"}:
                question["project_id"] = None
            if kind in {"introduction", "closing"}:
                question.update(scoring_guidance=None, strong_answer_signals=[], follow_ups=[])
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


def make_preparation(store, model):
    from backend.modules.pre_interview.preparation.planning import InterviewPlanner
    from backend.modules.pre_interview.preparation.service import PreparationService
    from backend.modules.pre_interview.profiles.service import ProfileService
    from backend.modules.pre_interview.resume_ingestion.pdf_extractor import PdfExtractor

    return PreparationService(
        store,
        ProfileService(model),
        InterviewPlanner(model),
        PdfExtractor(),
    )


class FakePreparation:
    def __init__(self, value):
        self.value = value

    async def get(self, candidate_id):
        return self.value.model_copy(deep=True)
