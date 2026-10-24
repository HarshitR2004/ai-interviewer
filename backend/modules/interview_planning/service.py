from pydantic import BaseModel

from backend.integrations.llm.contracts import StructuredGenerator
from backend.modules.profiles.models import CandidateProfile

from .models import InterviewPlan, InterviewSettings, RoleRequirements
from .planning import allocate_time, as_interview, explicit_competencies, planning_schema
from .prompts import PLANNER, ROLE_REQUIREMENTS
from .validation import validate_plan


class InterviewService:
    def __init__(self, model: StructuredGenerator):
        self.model = model

    async def create(
        self, persona: CandidateProfile, job_description: str, settings: InterviewSettings
    ) -> InterviewPlan:
        # Resolve competencies, then generate a mixed interview with validated coverage.
        competencies = explicit_competencies(job_description)
        if competencies is None:
            requirements = await self.model.generate(
                ROLE_REQUIREMENTS,
                {"job_description": job_description},
                RoleRequirements,
            )
            competencies = list(dict.fromkeys(requirements.competencies))
        schema = planning_schema(competencies)

        def check_plan(value: BaseModel) -> None:
            # Check domain rules inside generation so invalid output can use the repair attempt.
            plan = as_interview(value, competencies)
            allocate_time(plan, settings)
            validate_plan(plan, persona, settings)

        generated = await self.model.generate(
            PLANNER,
            {
                "candidate": persona.model_dump(),
                "job_description": job_description,
                "settings": settings.model_dump(),
                "required_sections": {
                    f"section_{index}": name for index, name in enumerate(competencies, start=1)
                },
            },
            schema,
            check_plan,
        )
        plan = as_interview(generated, competencies)
        allocate_time(plan, settings)
        validate_plan(plan, persona, settings)
        return plan
