"""Schema-specific Markdown codecs. Domain services never parse document syntax."""

from typing import Literal, cast

from pydantic import ValidationError

from backend.common.markdown import DocumentFormatError, Reader, Writer
from backend.modules.pre_interview.preparation.models import (
    InterviewPlan,
    InterviewSettings,
    Question,
    QuestionKind,
    ScoringGuidance,
    Section,
)
from backend.modules.pre_interview.preparation.validation import validate_plan
from backend.modules.pre_interview.profiles.models import CandidateProfile, Project
from backend.modules.pre_interview.profiles.validation import validate_profile


def render_profile(profile: CandidateProfile) -> str:
    # Serialize candidate data into the lossless Markdown document format.
    doc = Writer("Candidate Profile")
    doc.heading("Identity")
    doc.field("Name", profile.name)
    doc.field("Background", profile.background, 2)
    for name, values in [("Education", profile.education), ("Experience", profile.experience)]:
        doc.heading(name)
        doc.items(values)
    doc.heading("Skills")
    if not profile.skills:
        doc.items([])
    for number, (category, skills) in enumerate(profile.skills.items(), 1):
        doc.heading(f"Skill Group {number}", 3)
        doc.field("Category", category, 4)
        doc.heading("Skills", 4)
        doc.items(skills)
    doc.heading("Projects")
    if not profile.projects:
        doc.items([])
    for number, project in enumerate(profile.projects, 1):
        doc.heading(f"Project {number}", 3)
        for name, value in [
            ("ID", project.id),
            ("Name", project.name),
            ("Purpose", project.purpose),
        ]:
            doc.field(name, value, 4)
        for name, values in [
            ("Technologies", project.technologies),
            ("Contributions", project.contributions),
            ("Technical Details", project.technical_details),
            ("Source References", project.source_refs),
        ]:
            doc.heading(name, 4)
            doc.items(values)
    for name, values in [
        ("Discussion Topics", profile.discussion_topics),
        ("Source References", profile.source_references),
    ]:
        doc.heading(name)
        doc.items(values)
    doc.heading("Collection Status")
    if not profile.collection_status:
        doc.items([])
    for number, (source, status) in enumerate(profile.collection_status.items(), 1):
        doc.heading(f"Source {number}", 3)
        doc.field("Source", source, 4)
        doc.field("Status", status, 4)
    return doc.finish()


def parse_profile(content: str) -> CandidateProfile:
    # Rebuild and validate a profile from the expected Markdown structure.
    doc = Reader(content, "Candidate Profile")
    try:
        doc.heading("Identity")
        name = doc.field("Name")
        background = doc.field("Background", 2)
        doc.heading("Education")
        education = doc.items()
        doc.heading("Experience")
        experience = doc.items()
        doc.heading("Skills")
        skills: dict[str, list[str]] = {}
        for _ in doc.groups("Skill Group"):
            category = doc.field("Category", 4)
            if category in skills:
                raise DocumentFormatError("Duplicate skill category.")
            doc.heading("Skills", 4)
            skills[category] = doc.items()
        doc.heading("Projects")
        projects: list[Project] = []
        for _ in doc.groups("Project"):
            project_id, project_name, purpose = (
                doc.field("ID", 4),
                doc.field("Name", 4),
                doc.field("Purpose", 4),
            )
            lists: list[list[str]] = []
            for field in [
                "Technologies",
                "Contributions",
                "Technical Details",
                "Source References",
            ]:
                doc.heading(field, 4)
                lists.append(doc.items())
            projects.append(
                Project(
                    id=project_id,
                    name=project_name,
                    purpose=purpose,
                    technologies=lists[0],
                    contributions=lists[1],
                    technical_details=lists[2],
                    source_refs=lists[3],
                )
            )
        doc.heading("Discussion Topics")
        topics = doc.items()
        doc.heading("Source References")
        sources = doc.items()
        doc.heading("Collection Status")
        statuses: dict[str, str] = {}
        for _ in doc.groups("Source"):
            source = doc.field("Source", 4)
            if source in statuses:
                raise DocumentFormatError("Duplicate collection source.")
            statuses[source] = doc.field("Status", 4)
        doc.finish()
        profile = CandidateProfile(
            name=name,
            background=background,
            education=education,
            experience=experience,
            skills=skills,
            projects=projects,
            discussion_topics=topics,
            source_references=sources,
            collection_status=statuses,
        )
        validate_profile(profile, {"resume"})
        return profile
    except (ValueError, ValidationError) as exc:
        raise DocumentFormatError(
            "Invalid candidate profile document: check field values and project sources."
        ) from exc


def render_plan(plan: InterviewPlan, settings: InterviewSettings, job_description: str) -> str:
    # Save questions, rubrics, and preparation inputs in one Markdown document.
    doc = Writer("Interview Plan")
    doc.field("Role", plan.role, 2)
    doc.field("Plan Version", str(plan.format_version), 2)
    doc.heading("Interview Settings")
    for name, value in [
        ("Duration Minutes", str(settings.duration)),
        ("Seniority", settings.seniority),
    ]:
        doc.field(name, value)
    doc.field("Job Description", job_description, 2)
    doc.heading("Required Competencies")
    doc.items(plan.required_competencies)
    doc.heading("Sections")
    for number, section in enumerate(plan.sections, 1):
        question = section.questions[0]
        doc.heading(f"Section {number}", 3)
        for name, value in [
            ("Title", section.title),
            ("Competency", section.competency),
            ("Question Type", section.kind),
        ]:
            doc.field(name, value, 4)
        doc.heading("Covered Competencies", 4)
        doc.items(section.covered_competencies)
        for name, value in [
            ("Duration Minutes", str(section.minutes)),
            ("Question", question.question),
            ("Candidate Context", question.candidate_context),
        ]:
            doc.field(name, value, 4)
        doc.heading("Project ID", 4)
        if question.project_id is None:
            doc.lines.extend(["Not project-specific.", ""])
        else:
            doc.text(question.project_id)
        for name, values in [
            ("Follow-ups", question.follow_ups),
            ("Strong Answer Signals", question.strong_answer_signals),
        ]:
            doc.heading(name, 4)
            doc.items(values)
        doc.heading("Scoring Guidance", 4)
        if question.scoring_guidance is None:
            doc.lines.extend(["Not assessed.", ""])
            continue
        for name, value in [
            ("Weak", question.scoring_guidance.weak),
            ("Adequate", question.scoring_guidance.adequate),
            ("Strong", question.scoring_guidance.strong),
        ]:
            doc.field(name, value, 5)
    return doc.finish()


def parse_plan(
    content: str, profile: CandidateProfile
) -> tuple[InterviewPlan, InterviewSettings, str]:
    # Rebuild a saved plan and validate its references against the candidate profile.
    doc = Reader(content, "Interview Plan")
    try:
        role = doc.field("Role", 2)
        version = int(doc.field("Plan Version", 2)) if doc.peek() == "## Plan Version" else 1
        doc.heading("Interview Settings")
        settings = InterviewSettings.model_validate(
            {
                "duration": int(doc.field("Duration Minutes")),
                "seniority": doc.field("Seniority"),
            }
        )
        # Older saved plans included a user-selected type; all replans now use mixed.
        if doc.peek() == "### Interview Type":
            doc.field("Interview Type")
        jd = doc.field("Job Description", 2)
        doc.heading("Required Competencies")
        competencies = doc.items()
        doc.heading("Sections")
        sections: list[Section] = []
        for _ in doc.groups("Section"):
            title, competency = doc.field("Title", 4), doc.field("Competency", 4)
            kind = (
                doc.field("Question Type", 4)
                if doc.peek() == "#### Question Type"
                else "fundamentals"
            )
            coverage = []
            if doc.peek() == "#### Covered Competencies":
                doc.heading("Covered Competencies", 4)
                coverage = doc.items()
            minutes = int(doc.field("Duration Minutes", 4))
            question, context = doc.field("Question", 4), doc.field("Candidate Context", 4)
            doc.heading("Project ID", 4)
            project_id: str | None
            if doc.peek() == "Not project-specific.":
                doc.expect("Not project-specific.")
                project_id = None
            else:
                project_id = doc.text()
            doc.heading("Follow-ups", 4)
            follow_ups = doc.items()
            doc.heading("Strong Answer Signals", 4)
            signals = doc.items()
            doc.heading("Scoring Guidance", 4)
            scoring = None
            if doc.peek() == "Not assessed.":
                doc.expect("Not assessed.")
            else:
                scoring = ScoringGuidance(
                    weak=doc.field("Weak", 5),
                    adequate=doc.field("Adequate", 5),
                    strong=doc.field("Strong", 5),
                )
            sections.append(
                Section(
                    title=title,
                    competency=competency,
                    kind=cast(QuestionKind, kind),
                    covered_competencies=coverage,
                    minutes=minutes,
                    questions=[
                        Question(
                            question=question,
                            candidate_context=context,
                            project_id=project_id,
                            follow_ups=follow_ups,
                            strong_answer_signals=signals,
                            scoring_guidance=scoring,
                        )
                    ],
                )
            )
        doc.finish()
        plan = InterviewPlan(
            role=role,
            format_version=cast(Literal[1, 2], version),
            required_competencies=competencies,
            sections=sections,
        )
        validate_plan(plan, profile, settings)
        return plan, settings, jd
    except (ValueError, ValidationError) as exc:
        raise DocumentFormatError(
            "Invalid interview plan document: check settings, durations, competencies, questions, and project references."
        ) from exc
