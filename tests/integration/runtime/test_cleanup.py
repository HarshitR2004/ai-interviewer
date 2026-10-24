from fastapi.testclient import TestClient

from backend.bootstrap import build_services
from backend.main import create_app
from backend.settings import Settings


def test_clients_close_and_startup_does_not_touch_old_data(tmp_path):
    legacy = tmp_path / "v2/keep.json"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old data")
    closed = []

    def factory(config):
        services = build_services(config)
        original = services.aclose

        async def close():
            await original()
            closed.append(True)

        services.aclose = close
        return services

    config = Settings(
        _env_file=None, data_dir=tmp_path, llm_base_url="https://llm.example/v1", llm_model="test"
    )
    with TestClient(create_app(config, service_factory=factory)) as client:
        assert client.get("/openapi.json").status_code == 200
        assert not (tmp_path / "demo").exists()
    assert closed == [True]
    assert legacy.read_bytes() == b"old data"
