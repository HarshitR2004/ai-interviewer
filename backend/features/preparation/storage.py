import re
from pathlib import Path
from uuid import uuid4

from backend.shared.files import atomic_write, write_json

from .models import Status


class LocalStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def candidate(self, candidate_id: str) -> Path:
        if not re.fullmatch("[a-f0-9]{32}", candidate_id):
            raise FileNotFoundError(candidate_id)
        path = self.root / candidate_id
        if not path.is_dir():
            raise FileNotFoundError(candidate_id)
        return path

    def create(self) -> str:
        candidate_id = uuid4().hex
        path = self.root / candidate_id
        for sub in ("inputs", "structured"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        self.write_status(
            Status(candidate_id=candidate_id, state="queued", message="Your preparation is queued.")
        )
        return candidate_id

    @staticmethod
    def write(path: Path, content: str | bytes) -> None:
        atomic_write(path, content)

    def json(self, path: Path, content: dict) -> None:
        write_json(path, content)

    def write_status(self, status: Status) -> None:
        self.json(self.candidate(status.candidate_id) / "status.json", status.model_dump())

    def status(self, candidate_id: str) -> Status:
        return Status.model_validate_json(
            (self.candidate(candidate_id) / "status.json").read_text(encoding="utf-8")
        )

    def recover(self) -> None:
        for path in self.root.glob("*/status.json"):
            status = Status.model_validate_json(path.read_text(encoding="utf-8"))
            if status.state not in {"completed", "failed"}:
                status.state = "failed"
                status.message = "Preparation was interrupted. Please submit again."
                self.write_status(status)
