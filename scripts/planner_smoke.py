"""Exercise the configured planner with a synthetic candidate and the configured sample JD."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.integrations.llm.client import ChatCompletionsClient
from backend.integrations.llm.structured_generation import StructuredGeneration
from backend.modules.pre_interview.preparation.documents import parse_plan, render_plan
from backend.modules.pre_interview.preparation.models import InterviewSettings
from backend.modules.pre_interview.preparation.planning import InterviewPlanner
from backend.modules.pre_interview.profiles.models import CandidateProfile, Project
from backend.settings import Settings


async def main() -> None:
    settings = Settings.model_validate({})
    client = ChatCompletionsClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
    persona = CandidateProfile(
        name="Synthetic Candidate",
        background="Computer science student learning applied ML",
        education=["Studying computer science"],
        experience=[],
        skills={"Programming": ["Python"], "Libraries": ["pandas", "scikit-learn"]},
        projects=[
            Project(
                id="sample-project",
                name="Spam classifier",
                purpose="Classify sample messages as spam or not spam",
                technologies=["Python", "pandas", "scikit-learn"],
                contributions=["Cleaned a public text dataset and trained a baseline classifier"],
                technical_details=["Used a train/test split and compared precision and recall"],
                source_refs=["resume"],
            )
        ],
        discussion_topics=["Data cleaning", "Model evaluation"],
        source_references=["resume"],
        collection_status={},
    )
    options = InterviewSettings(duration=15, seniority="junior")
    jd = Path("sample_data/job_description.txt").read_text(encoding="utf-8")
    print("Generating a 15-minute plan using synthetic candidate data…", flush=True)
    try:
        plan = await asyncio.wait_for(
            InterviewPlanner(StructuredGeneration(client)).create(persona, jd, options), 240
        )
        assert parse_plan(render_plan(plan, options, jd), persona)[0] == plan
        output = Path("work/planner-smoke.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        for section in plan.sections:
            print(
                f"{section.kind} ({section.minutes}m): {section.questions[0].question}", flush=True
            )
        print(f"Validated plan saved to {output}", flush=True)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
