"""Model bağlantıları ve aktif model seçimi.

Uygulama her zaman OpenAI-uyumlu bir `/chat/completions` uç noktasıyla konuşur.
Bağlantılar (yerel Ollama, LM Studio, vLLM, isteğe bağlı bir bulut servisi) kullanıcı
arayüzünden yönetilir ve `DATA_DIR/model_ayarlari.json` dosyasında saklanır.
Bu dosya git'e girmez; API anahtarları yalnız orada durur ve API yanıtlarında
asla geri gönderilmez (yalnız "anahtar var mı" bilgisi döner).

Dosya yoksa ortam değişkenleri (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY) varsayılandır.
"""
from __future__ import annotations

import json
import os
import re
import threading

import httpx

from . import config

_lock = threading.Lock()


def _path():
    return config.DATA_DIR / "model_ayarlari.json"


def _defaults() -> dict:
    return {
        "baglantilar": [
            {"id": "yerel", "ad": "Yerel model", "tur": "yerel",
             "base_url": config.LLM_BASE_URL, "api_key": config.LLM_API_KEY if config.LLM_API_KEY != "local" else ""},
            {"id": "anthropic", "ad": "Anthropic Claude", "tur": "bulut",
             "base_url": "https://api.anthropic.com/v1", "api_key": ""},
        ],
        "aktif": {"baglanti": "yerel", "model": config.LLM_MODEL},
    }


def load() -> dict:
    p = _path()
    if not p.exists():
        return _defaults()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("baglantilar") and data.get("aktif"):
            return data
    except Exception:
        pass
    return _defaults()


def save(data: dict) -> None:
    p = _path()
    with _lock:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(p)


def _find(data: dict, conn_id: str) -> dict | None:
    return next((b for b in data["baglantilar"] if b["id"] == conn_id), None)


def active() -> dict:
    """Aktif bağlantı + model: {id, ad, tur, base_url, api_key, model}."""
    data = load()
    a = data["aktif"]
    b = _find(data, a.get("baglanti")) or data["baglantilar"][0]
    return {**b, "model": a.get("model") or ""}


def headers(conn: dict) -> dict:
    key = conn.get("api_key") or "local"
    h = {"Authorization": f"Bearer {key}"}
    if "anthropic.com" in (conn.get("base_url") or ""):
        # Anthropic'in OpenAI-uyumlu katmanı Bearer kabul eder; /models yerel başlıkları ister.
        h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    return h


def public(conn: dict) -> dict:
    """API'ye dönecek hâl: anahtarın kendisi asla yok."""
    out = {k: v for k, v in conn.items() if k != "api_key"}
    out["anahtar_var"] = bool(conn.get("api_key"))
    return out


def list_models(conn: dict, timeout: float = 4) -> tuple[list[str], str | None]:
    """Bağlantıdaki modelleri listeler. (modeller, hata) döner."""
    try:
        r = httpx.get(f"{conn['base_url'].rstrip('/')}/models", headers=headers(conn), timeout=timeout)
        if r.status_code == 401 or r.status_code == 403:
            return [], "Anahtar geçersiz ya da eksik."
        r.raise_for_status()
        items = r.json().get("data", [])
        return sorted({m.get("id") for m in items if m.get("id")}), None
    except httpx.ConnectError:
        return [], "Sunucuya ulaşılamadı."
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)[:160]


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "baglanti"


def upsert_connection(data: dict, body: dict) -> dict:
    """Bağlantı ekler ya da günceller. api_key boş/None gelirse mevcut anahtar korunur."""
    conn = _find(data, body.get("id") or "")
    if conn is None:
        base = slug(body.get("ad") or "baglanti")
        cid, n = base, 2
        while _find(data, cid):
            cid, n = f"{base}-{n}", n + 1
        conn = {"id": cid, "ad": "", "tur": body.get("tur") or "yerel", "base_url": "", "api_key": ""}
        data["baglantilar"].append(conn)
    for k in ("ad", "tur", "base_url"):
        if body.get(k):
            conn[k] = body[k].strip()
    if body.get("api_key") is not None and body.get("api_key") != "":
        conn["api_key"] = body["api_key"].strip()
    if body.get("anahtari_sil"):
        conn["api_key"] = ""
    return conn
