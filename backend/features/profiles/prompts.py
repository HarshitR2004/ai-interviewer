PROFILE = """Organize the candidate's supplied information into a concise technical profile.
Accept supplied candidate information as accurate. Do not verify it or infer personality.
Use only provided content. Missing details stay empty. Never infer years of employment from account age.
Use stable project IDs p1, p2, etc. Source references must be resume.
Merge duplicate projects. Group skills by area. Exclude provider rankings, activity scores, contact
details, inferred location and hiring recommendations. Limit to 6 relevant projects and 8 discussion topics.
Collection status and source limitations will be attached by the application.
Extract each project as its own self-contained block from the input. Keep every technology,
metric, feature, and contribution attached to the project where it is stated. Never transfer a
detail from a neighboring project. Prefer exact wording over creative paraphrasing. Do not add
plausible extensions, deployment targets, architectures, or features that the source does not state.
For project.source_refs use only labels in allowed_sources, exactly as given. Do not use generic
labels for external sources. Use resume for project descriptions from the resume.
"""
