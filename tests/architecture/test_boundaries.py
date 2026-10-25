import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def imports(path):
    package = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                pieces = package.split(".")
                prefix = ".".join(
                    pieces[: len(pieces) - node.level + 1] + ([prefix] if prefix else [])
                )
            yield prefix
            yield from (prefix + "." + item.name for item in node.names)


def test_dependency_boundaries():
    for path in BACKEND.rglob("*.py"):
        relative = path.relative_to(BACKEND)
        for module in imports(path):
            assert not module.startswith(("backend.web", "backend.runtime", "backend.shared")), (
                path,
                module,
            )
            if relative.parts[0] in {"integrations", "common"}:
                assert not module.startswith(
                    ("backend.modules", "backend.api", "backend.bootstrap")
                ), (path, module)
            if relative.parts[0] == "modules":
                assert not module.startswith(("backend.api", "backend.bootstrap")), (path, module)
                if relative.parts[1] == "pre_interview":
                    assert not module.startswith("backend.modules.live_interviews"), (path, module)
                if path.stem in {"models", "validation", "transitions"}:
                    assert not module.startswith(
                        (
                            "fastapi",
                            "httpx",
                            "sqlite3",
                            "pathlib",
                            "backend.modules.pre_interview.preparation.documents",
                        )
                    ), (path, module)
                if path.name == "service.py":
                    assert not module.endswith((".storage", ".documents")), (path, module)
            if relative.parts[:2] == ("api", "routes"):
                assert not module.endswith((".storage", ".documents", ".client")), (path, module)


def test_no_retired_persistence_or_frontend():
    for name in [
        "runtime",
        "api/schemas",
        "modules/live_interviews/adapters",
        "modules/pre_interview/preparation/adapters",
    ]:
        assert not list((BACKEND / name).rglob("*.py"))
    for path in BACKEND.rglob("*.py"):
        source = path.read_text()
        assert "sqlite3" not in source
        if path.name in {"storage.py", "documents.py"} and "pre_interview" in path.parts:
            assert "import json" not in source and "model_dump_json" not in source
    for extension in ["*.html", "*.js", "*.css"]:
        assert not list(BACKEND.rglob(extension))


def test_relative_import_resolution():
    assert "backend.modules.live_interviews.models" in set(
        imports(BACKEND / "modules/live_interviews/service.py")
    )


def test_pre_interview_modules_have_one_location():
    assert not (BACKEND / "modules/pre_interview/interview_planning").exists()
    for name in ("preparation", "profiles", "resume_ingestion"):
        assert (BACKEND / "modules/pre_interview" / name / "__init__.py").is_file()
        assert not (BACKEND / "modules" / name).exists()
