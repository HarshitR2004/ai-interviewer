from uuid import uuid4

from backend.common.errors import Conflict
from backend.modules.pre_interview.profiles.models import CandidateProfile
from backend.modules.pre_interview.profiles.service import ProfileService
from backend.modules.pre_interview.resume_ingestion.pdf_extractor import PdfExtractor, ResumeUpload

from .models import Preparation, PreparationInputs
from .planning import InterviewPlanner
from .ports import PreparationStore


class PreparationService:
    def __init__(
        self,
        store: PreparationStore,
        profiles: ProfileService,
        interviews: InterviewPlanner,
        ingestion: PdfExtractor,
    ):
        self._store, self._profiles = store, profiles
        self._interviews, self._ingestion = interviews, ingestion
        self._busy: set[str] = set()

    async def submit(self, upload: ResumeUpload, inputs: PreparationInputs) -> Preparation:
        # Extract the resume, generate both artifacts, and persist before reporting success.
        text = await self._ingestion.ingest(upload)
        profile = await self._profiles.create(text)
        result = await self._prepare(uuid4().hex, profile, inputs)
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
            result = await self._prepare(candidate_id, current.profile, inputs)
            await self._store.replace_plan(result)
            return result
        finally:
            self._busy.remove(candidate_id)

    async def _prepare(
        self, candidate_id: str, profile: CandidateProfile, inputs: PreparationInputs
    ) -> Preparation:
        plan = await self._interviews.create(profile, inputs.job_description, inputs.settings)
        return Preparation(
            candidate_id=candidate_id,
            profile=profile,
            plan=plan,
            settings=inputs.settings,
            job_description=inputs.job_description,
        )
