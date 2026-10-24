from fastapi.testclient import TestClient

from backend.bootstrap import build_services
from backend.main import create_app
from backend.settings import Settings


def test_clients_close_and_startup_does_not_touch_old_data(tmp_path):
    legacy = tmp_path / "v2/keep.json"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old data")
    config = Settings(
        _env_file=None, data_dir=tmp_path, llm_base_url="https://llm.example/v1", llm_model="test"
    )
    services = build_services(config)
    assert services.model is not None
    with TestClient(create_app(services)) as client:
        assert client.get("/openapi.json").status_code == 200
        assert not (tmp_path / "demo").exists()
    assert services.model._client.is_closed
    assert legacy.read_bytes() == b"old data"
