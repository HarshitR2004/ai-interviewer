from backend.shared.markdown import bullets

from .models import Persona


def render_persona(profile: Persona) -> str:
    parts = [
        f"# {profile.name}\n\n{profile.background}",
        "## Education\n" + bullets(profile.education),
        "## Experience\n" + bullets(profile.experience),
        "## Skills",
    ]
    parts.extend(f"### {area}\n{bullets(skills)}" for area, skills in profile.skills.items())
    parts.append("## Projects")
    for project in profile.projects:
        parts.append(
            f"### {project.name} ({project.id})\n{project.purpose}\n\nTechnologies: {', '.join(project.technologies)}\n\nContributions:\n{bullets(project.contributions)}\n\nTechnical details:\n{bullets(project.technical_details)}\n\nSources: {', '.join(project.source_refs)}"
        )
    parts.extend(
        [
            "## Discussion topics\n" + bullets(profile.discussion_topics),
            "## Sources\n" + bullets(profile.source_references),
            "## Collection status\n"
            + bullets([f"{key}: {value}" for key, value in profile.collection_status.items()]),
        ]
    )
    return "\n\n".join(parts) + "\n"
