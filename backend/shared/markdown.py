def bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- Not provided."
