"""OpenAI-uyumlu (lokal) LLM uç noktasına çağrı.

Sabit bir cloud API key YOK. Uç nokta app/config.py üzerinden ortam
değişkenleriyle yapılandırılır (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY).
Bağlantı kurulamazsa uygulama çökmez; çağıran taraf açık bir hata/durum alır.
"""
import json

import httpx

from . import config

SUGGESTION_SYSTEM_PROMPT = """Sen bir bankanın iç kontrol biriminde çalışan, periyodik \
kontrol önerileri üreten bir uzmansın. Sana iki şey verilecek: (1) şirketin yüklediği süreç/\
prosedür belgelerinden çıkarılmış metin, (2) birikmiş "skill" bilgi tabanı (mevzuat, \
Üçlü Savunma Hattı, MASAK/AML kuralları, kontrol metrikleri tanımları).

Görevin: belgedeki süreçler için somut periyodik kontrol ÖNERİLERİ üretmek. Her öneri şu \
alanları İÇERMELİDİR ve SADECE geçerli bir JSON listesi olarak dönmelisin (başka hiçbir \
metin yazma):

[
  {
    "kontrol_adi": "...",
    "kategori": "...",
    "hat": "yalnızca tek bir rakam: 1, 2 veya 3",
    "siklik": "...",
    "risk": "düşük | orta | yüksek | kritik",
    "efor": "düşük | orta | yüksek",
    "gerekce": "belge/mevzuat referansıyla kısa gerekçe"
  }
]

MASAK/AML kategorisindeki önerilere tipping-off uyarısını gerekçeye ekle. Belgede boşluk \
(gap) görürsen gerekçede açıkça belirt."""


def call_chat_completion(messages: list[dict], temperature: float = 0.2) -> dict:
    """Döner: {"ok": True, "content": str} veya {"ok": False, "error": str}."""
    url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    try:
        with httpx.Client(timeout=config.LLM_TIMEOUT_S) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "content": data["choices"][0]["message"]["content"]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def generate_suggestions(document_text: str, skills_text: str) -> dict:
    """LLM'den öneri listesi ister. Başarısızlıkta hata bilgisini döner, uygulama çökmez."""
    user_prompt = (
        f"BİRİKMİŞ SKILL BİLGİSİ:\n{skills_text}\n\n"
        f"ŞİRKET BELGESİNDEN ÇIKARILAN METİN (ilk ~12000 karakter):\n"
        f"{document_text[:12000]}\n\n"
        "Yukarıdaki talimata göre JSON listesi üret."
    )
    result = call_chat_completion(
        [
            {"role": "system", "content": SUGGESTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    if not result["ok"]:
        return {
            "ok": False,
            "error": (
                "Lokal LLM uç noktasına ulaşılamadı "
                f"({config.LLM_BASE_URL}): {result['error']}. "
                "LLM_BASE_URL / LLM_MODEL ortam değişkenlerini işyerindeki "
                "lokal model sunucunuza göre ayarlayın."
            ),
        }
    content = result["content"]
    try:
        # Model bazen kod bloğu içine sarabilir; temizle.
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            if cleaned.lower().startswith("json"):
                cleaned = cleaned.split("\n", 1)[1]
        suggestions = json.loads(cleaned)
        return {"ok": True, "suggestions": suggestions}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Model yanıtı JSON olarak ayrıştırılamadı: {exc}",
            "raw_response": content,
        }
