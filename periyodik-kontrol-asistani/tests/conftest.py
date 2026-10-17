import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Uygulama import edilmeden önce geçici bir veri klasörüne yönlendir.
_TMP = Path(tempfile.mkdtemp(prefix="pka-test-"))
os.environ["PKA_DATA_DIR"] = str(_TMP)

from fake_llm import FakeLLM  # noqa: E402
from app import config, storage  # noqa: E402

SEED_SKILLS = ROOT / "app" / "seed_skills"
if not SEED_SKILLS.exists():  # adım 3'ten önceki düzen
    SEED_SKILLS = ROOT / "data" / "skills"


@pytest.fixture(scope="session")
def fake_llm():
    f = FakeLLM().start()
    yield f
    f.stop()


@pytest.fixture()
def env(tmp_path, fake_llm, monkeypatch):
    """Her test için temiz veri klasörü, temiz veritabanı ve sahte model."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(config, "KAYNAK_DIR", tmp_path / "kaynaklar")
    monkeypatch.setattr(config, "LLM_BASE_URL", fake_llm.base_url)
    monkeypatch.setattr(config, "LLM_MODEL", "fake-model")
    (tmp_path / "uploads").mkdir()
    shutil.copytree(SEED_SKILLS, tmp_path / "skills")
    storage.init_db()
    fake_llm.calls.clear()
    fake_llm.status = 200
    fake_llm.responder = lambda messages, stream: ""
    return fake_llm


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def read_ndjson(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def wait_set(client, set_id, timeout=15.0) -> dict:
    """Arka plan üretiminin bitmesini bekler, tam seti döner."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/sets/{set_id}/progress?after=999999").json()
        if s["durum"] != "uretiliyor":
            from app import jobs
            for _ in range(50):  # iş parçacığının tamamen çıkmasını bekle
                if not jobs.is_running():
                    break
                time.sleep(0.02)
            return client.get(f"/api/sets/{set_id}").json()
        time.sleep(0.05)
    raise AssertionError("üretim zamanında bitmedi")


def jsonl(*objs) -> str:
    return "\n".join(json.dumps(o, ensure_ascii=False) for o in objs) + "\n"
