from backend.features.profiles.models import Persona
from backend.shared.ports import LanguageModel

from .models import InterviewPlan, InterviewSettings, RoleRequirements
from .planning import ROLE_REQUIREMENTS, as_interview, explicit_competencies, planning_schema
from .prompts import PLANNER
from .validation import allocate_time, validate_plan


class InterviewService:
    def __init__(self, model: LanguageModel):
        self.model = model

    async def create(
        self, persona: Persona, job_description: str, settings: InterviewSettings
    ) -> InterviewPlan:
        competencies = explicit_competencies(job_description)
        if competencies is None:
            requirements = await self.model.generate(
                ROLE_REQUIREMENTS, {"job_description": job_description}, RoleRequirements
            )
            competencies = list(dict.fromkeys(requirements.competencies))
        schema = planning_schema(competencies)

        def check_plan(value):
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
