from uuid import uuid4

from backend.common.errors import Conflict
from backend.modules.pre_interview.interview_planning.service import InterviewService
from backend.modules.pre_interview.profiles.service import ProfileService
from backend.modules.pre_interview.resume_ingestion.service import (
    ResumeIngestionService,
    ResumeUpload,
)

from .models import Preparation, PreparationInputs
from .ports import PreparationStore


class PreparationService:
    def __init__(
        self,
        store: PreparationStore,
        profiles: ProfileService,
        interviews: InterviewService,
        ingestion: ResumeIngestionService,
    ):
        self._store, self._profiles = store, profiles
        self._interviews, self._ingestion = interviews, ingestion
        self._busy: set[str] = set()

    async def submit(self, upload: ResumeUpload, inputs: PreparationInputs) -> Preparation:
        # Extract the resume, generate both artifacts, and persist before reporting success.
        text = await self._ingestion.extract(upload)
        profile = await self._profiles.create(text)
        plan = await self._interviews.create(profile, inputs.job_description, inputs.settings)
        result = Preparation(
            candidate_id=uuid4().hex,
            profile=profile,
            plan=plan,
            settings=inputs.settings,
            job_description=inputs.job_description,
        )
        await self._store.create(result, upload.content)
        return result

    async def get(self, candidate_id: str) -> Preparation:
        # Prevent reads during replanning, then reload the completed preparation.
        if candidate_id in self._busy:
            raise Conflict("This candidate is being replanned.")
        return await self._store.load(candidate_id)

    async def replan(self, candidate_id: str, inputs: PreparationInputs) -> Preparation:
        # Keep the profile and replace the plan only after successful generation.
        if candidate_id in self._busy:
            raise Conflict("This candidate is being replanned.")
        self._busy.add(candidate_id)
        try:
            current = await self._store.load(candidate_id)
            plan = await self._interviews.create(
                current.profile, inputs.job_description, inputs.settings
            )
            result = Preparation(
                candidate_id=candidate_id,
                profile=current.profile,
                plan=plan,
                settings=inputs.settings,
                job_description=inputs.job_description,
            )
            await self._store.replace_plan(result)
            return result
        finally:
            self._busy.remove(candidate_id)
