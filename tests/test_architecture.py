import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def test_feature_dependency_boundaries():
    allowed = {
        "collection": {"collection"},
        "profiles": {"profiles"},
        "interviews": {"interviews", "profiles"},
        "preparation": {"collection", "profiles", "interviews", "preparation"},
        "live_interviews": {"live_interviews", "interviews"},
        "speech": {"speech"},
    }
    for path in BACKEND.rglob("*.py"):
        relative = path.relative_to(BACKEND)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                assert not module.startswith(
                    (
                        "backend.application",
                        "backend.domain",
                        "backend.infrastructure",
                        "backend.presentation",
                    )
                ), (path, module)
                if relative.parts[0] == "shared":
                    assert not module.startswith(
                        ("backend.features", "backend.web", "backend.main")
                    ), (path, module)
                if relative.parts[0] == "features":
                    assert not module.startswith(("backend.web", "backend.main")), (path, module)
                    if module.startswith("backend.features."):
                        target = module.split(".")[2]
                        assert target in allowed[relative.parts[1]], (path, module)
                        if relative.parts[1] == "interviews" and target == "profiles":
                            assert module == "backend.features.profiles.models", (path, module)
                        if relative.parts[1] == "live_interviews" and target == "interviews":
                            assert module == "backend.features.interviews.models", (path, module)
