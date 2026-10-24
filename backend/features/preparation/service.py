import logging

from backend.features.interviews.models import InterviewSettings
from backend.features.interviews.rendering import render_interview
from backend.features.interviews.service import InterviewService
from backend.features.profiles.models import Persona
from backend.features.profiles.rendering import render_persona
from backend.features.profiles.service import ProfileService
from backend.shared.errors import WorkflowError

from .models import Status
from .ports import CandidateStore

logger = logging.getLogger(__name__)


class PreparationService:
    def __init__(
        self,
        store: CandidateStore,
        profiles: ProfileService,
        interviews: InterviewService,
    ):
        self.store = store
        self.profiles = profiles
        self.interviews = interviews
        self.active: set[str] = set()

    def update(self, candidate_id, state, message, warnings=None):
        self.store.write_status(
            Status(candidate_id=candidate_id, state=state, message=message, warnings=warnings or [])
        )

    async def prepare(
        self,
        candidate_id: str,
        resume_text: str,
        jd: str,
        settings: InterviewSettings,
    ):
        path = self.store.candidate(candidate_id)
        warnings = []
        try:
            self.update(candidate_id, "profiling", "Preparing candidate profile.", warnings)
            persona = await self.profiles.create(resume_text)
            self.store.json(path / "structured/persona.json", persona.model_dump())
            self.store.write(path / "persona.md", render_persona(persona))
            await self.plan(candidate_id, persona, jd, settings, warnings)
        except Exception as exc:
            self.fail(candidate_id, exc, warnings)
        finally:
            self.active.discard(candidate_id)

    async def plan(self, candidate_id, persona, jd, settings, warnings):
        self.update(candidate_id, "planning", "Preparing interview.", warnings)
        plan = await self.interviews.create(persona, jd, settings)
        path = self.store.candidate(candidate_id)
        self.store.json(path / "structured/interview.json", plan.model_dump())
        self.store.write(path / "interview.md", render_interview(plan))
        self.store.write(path / "inputs/job_description.txt", jd)
        self.store.json(path / "inputs/settings.json", settings.model_dump())
        self.update(
            candidate_id, "completed", "Preparation complete. Your files have been saved.", warnings
        )

    async def replan(self, candidate_id, jd, settings):
        try:
            path = self.store.candidate(candidate_id)
            persona = Persona.model_validate_json(
                (path / "structured/persona.json").read_text(encoding="utf-8")
            )
            warnings = self.store.status(candidate_id).warnings
            await self.plan(candidate_id, persona, jd, settings, warnings)
        except Exception as exc:
            self.fail(candidate_id, exc)
        finally:
            self.active.discard(candidate_id)

    def fail(self, candidate_id, exc, warnings=None):
        logger.error("Preparation failed for %s (%s)", candidate_id, type(exc).__name__)
        message = (
            str(exc)
            if isinstance(exc, WorkflowError)
            else "Preparation could not finish. Please try again."
        )
        self.update(candidate_id, "failed", message, warnings)
