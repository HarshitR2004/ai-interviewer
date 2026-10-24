from .models import CandidateProfile


def validate_profile(persona: CandidateProfile, allowed_sources: set[str]) -> None:
    ids = [project.id for project in persona.projects]
    if len(ids) != len(set(ids)):
        raise ValueError("Project IDs must be unique.")
    for project in persona.projects:
        if not set(project.source_refs) <= allowed_sources:
            raise ValueError(
                f"Project sources must use only these exact labels: {sorted(allowed_sources)}."
            )
