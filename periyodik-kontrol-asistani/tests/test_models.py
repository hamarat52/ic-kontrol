"""Model bağlantıları ve aktif model seçimi."""
import json

from app import config, model_settings


def test_defaults_come_from_env(client, env):
    r = client.get("/api/models").json()
    ids = [b["id"] for b in r["baglantilar"]]
    assert ids == ["yerel", "anthropic"]
    yerel = r["baglantilar"][0]
    assert yerel["modeller"] == ["fake-model", "fake-model-2"] and yerel["hata"] is None
    assert r["aktif"] == {"baglanti": "yerel", "model": "fake-model"}
    assert r["baglantilar"][1]["hata"] == "Anahtar girilmedi."


def test_switch_model_is_used_for_generation(client, env):
    assert client.post("/api/models/active", json={"baglanti": "yerel", "model": "fake-model-2"}).status_code == 200
    client.post("/api/documents", files={"file": ("p.txt", "1. A\nmetin\n".encode(), "text/plain")})
    env.responder = lambda m, stream: '{"tip":"kontrol","kontrol_adi":"K"}\n' if stream else '{"baslik":"B","ozet":"O"}'
    from conftest import wait_set
    s = wait_set(client, client.post("/api/sets").json()["id"])
    assert s["model"] == "fake-model-2"
    assert {c["model"] for c in env.calls} == {"fake-model-2"}
    assert client.get("/api/health").json()["llm_model"] == "fake-model-2"


def test_api_key_never_returned_and_kept_on_update(client, env):
    secret = "test-anahtar-123"
    r = client.post("/api/models/connections", json={"ad": "Uzak sunucu", "tur": "bulut",
                                                     "base_url": env.base_url, "api_key": secret}).json()
    assert secret not in json.dumps(r)
    cid = r["id"]
    item = next(b for b in r["baglantilar"] if b["id"] == cid)
    assert item["anahtar_var"] is True and item["modeller"] == ["fake-model", "fake-model-2"]
    # anahtarsız güncelleme anahtarı silmez
    client.post("/api/models/connections", json={"id": cid, "ad": "Yeni ad"})
    stored = model_settings.load()
    conn = next(b for b in stored["baglantilar"] if b["id"] == cid)
    assert conn["api_key"] == secret and conn["ad"] == "Yeni ad"
    # sunucuya giden istekte anahtar Bearer olarak taşınır
    client.post("/api/models/active", json={"baglanti": cid, "model": "fake-model"})
    env.responder = lambda m, stream: json.dumps({"degisiklikler": [], "yanit": "ok", "ogrenilen": ""})
    assert model_settings.headers(model_settings.active())["Authorization"] == f"Bearer {secret}"
    # kullanımdaki bağlantı silinemez, yerel hiç silinemez
    assert client.delete(f"/api/models/connections/{cid}").status_code == 409
    assert client.delete("/api/models/connections/yerel").status_code == 400


def test_settings_file_is_private(client, env):
    client.post("/api/models/active", json={"baglanti": "yerel", "model": "fake-model"})
    p = config.DATA_DIR / "model_ayarlari.json"
    assert p.exists() and (p.stat().st_mode & 0o077) == 0


def test_validation(client, env):
    assert client.post("/api/models/connections", json={"ad": "x", "base_url": "ftp://a"}).status_code == 400
    assert client.post("/api/models/connections", json={"ad": "x"}).status_code == 400
    assert client.post("/api/models/active", json={"baglanti": "yok", "model": "m"}).status_code == 404
    assert client.post("/api/models/active", json={"baglanti": "yerel", "model": " "}).status_code == 400


def test_anthropic_headers():
    h = model_settings.headers({"base_url": "https://api.anthropic.com/v1", "api_key": "k"})
    assert h["x-api-key"] == "k" and h["anthropic-version"] and h["Authorization"] == "Bearer k"
    assert "x-api-key" not in model_settings.headers({"base_url": "http://localhost:11434/v1", "api_key": ""})
