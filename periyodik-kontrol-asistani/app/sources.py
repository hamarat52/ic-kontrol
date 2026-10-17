"""Belge türleri, alanlar ve uygulamayla gelen açık kaynaklar.

Türler:
- esas          Uygulama esası (kapalı kaynak) — kontroller bunlardan üretilir
- organizasyon  Organizasyon / görev tanımları (kapalı, isteğe bağlı) — sorumlu birim ve hat için bağlam
- resmi         Resmi düzenleme, Türkiye (açık) — dayanak
- global        Global standart (açık) — dayanak
- lisansli      Kurumun yüklediği lisanslı standart (COSO, ISO…) — dayanak

Açık kaynaklar app/kaynaklar/kaynaklar.json'dan okunur ve veritabanındaki documents
tablosuna "yerleşik" (silinemez) satırlar olarak eşitlenir.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from . import config, processing, retrieval

TURLER = {
    "esas": "Uygulama esası",
    "organizasyon": "Organizasyon ve görevler",
    "resmi": "Resmi düzenleme · Türkiye",
    "global": "Global standart",
    "lisansli": "Lisanslı standart",
}
URETEN = {"esas"}
DAYANAK = {"resmi", "global", "lisansli"}
KULLANICI_TURLERI = ("esas", "organizasyon", "lisansli")   # kullanıcının yükleyebileceği türler

ALAN_IKON = {
    "Kurumsal Yönetim ve İç Sistemler": "🏛️",
    "Kredi": "🏦",
    "Ödeme Sistemleri": "💸",
    "Bilgi Sistemleri ve Veri Güvenliği": "🛡️",
    "AML / Uyum": "🔍",
    "Kişisel Verilerin Korunması": "🔐",
    "Muhasebe ve Finansal Raporlama": "🧾",
    "Dış Hizmet Alımı": "🤝",
    "Operasyonel Risk ve İş Sürekliliği": "⚙️",
}


def _dir() -> Path:
    return Path(config.KAYNAK_DIR)


def manifest() -> dict:
    p = _dir() / "kaynaklar.json"
    if not p.exists():
        return {"alanlar": list(ALAN_IKON), "kaynaklar": [], "lisansli_eklenemeyenler": []}
    return json.loads(p.read_text(encoding="utf-8"))


def alanlar() -> list[str]:
    return manifest().get("alanlar") or list(ALAN_IKON)


def _indirme() -> dict:
    p = _dir() / "indirme.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def sync_builtin(conn) -> int:
    """Manifest'teki ve diskte metni olan açık kaynakları documents tablosuna eşitler."""
    info = _indirme()
    keep = []
    for k in manifest().get("kaynaklar", []):
        txt = _dir() / "metin" / f"{k['id']}.txt"
        if not txt.exists():
            continue
        keep.append(k["id"])
        meta = info.get(k["id"], {})
        orj = _dir() / "orijinal" / meta.get("orijinal", "")
        text = txt.read_text(encoding="utf-8")
        sha = hashlib.sha256(text.encode()).hexdigest()
        row = conn.execute("SELECT id, sha FROM documents WHERE kaynak_id = ?", (k["id"],)).fetchone()
        values = dict(filename=k["ad"], stored_path=str(txt), orijinal_path=str(orj) if orj.is_file() else None,
                      text_excerpt=text[:2000], char_count=len(text.strip()), tur=k["tur"],
                      alanlar=json.dumps(k.get("alanlar", []), ensure_ascii=False), kurum=k.get("kurum"),
                      kaynak_url=meta.get("url"), yerlesik=1, onerildi=0, sha=sha,
                      uploaded_at=(meta.get("erisim_tarihi") or "") + " 00:00:00" if meta.get("erisim_tarihi") else None)
        if row and row["sha"] == sha:
            # metin aynı: yalnız manifest kaynaklı alanları tazele
            conn.execute("UPDATE documents SET filename=?, tur=?, alanlar=?, kurum=?, kaynak_url=?, orijinal_path=? WHERE id=?",
                         (values["filename"], values["tur"], values["alanlar"], values["kurum"], values["kaynak_url"],
                          values["orijinal_path"], row["id"]))
            continue
        values["bolum"] = len(retrieval.split_pieces(text))
        if row:
            conn.execute(f"UPDATE documents SET {', '.join(f'{c} = ?' for c in values)} WHERE id = ?",
                         (*values.values(), row["id"]))
        else:
            values["kaynak_id"] = k["id"]
            conn.execute(f"INSERT INTO documents ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                         tuple(values.values()))
    q = ",".join("?" * len(keep)) or "''"
    conn.execute(f"DELETE FROM documents WHERE yerlesik = 1 AND kaynak_id NOT IN ({q})", keep)
    return len(keep)


# ------------------------------------------------------------------ sınıflandırma önerisi

# Alan başına anahtar kelimeler (kök hâlinde; eşleşme normalize edilmiş metinde kelime başından yapılır)
ALAN_SOZLUK = {
    "Kredi": "kredi tahsis teminat kullandir limit ipotek kefil temerrut takipteki istihbarat kredi komite",
    "Ödeme Sistemleri": "odeme transfer eft havale fast swift talimat kart pos elektronik para muhabir virman",
    "Bilgi Sistemleri ve Veri Güvenliği": "erisim yetki kullanici parola sifre log siber bilgi guvenligi ayricalikli "
                                          "yedek sizma veri guvenligi kimlik dogrulama zafiyet sunucu",
    "AML / Uyum": "aklama masak supheli musteri tanima yaptirim teror finansman kyc uyum gorevlisi",
    "Kişisel Verilerin Korunması": "kisisel veri kvkk acik riza anonim imha ilgili kisi veri sorumlusu",
    "Muhasebe ve Finansal Raporlama": "muhasebe mutabakat bilanco finansal tablo raporlama defter hesap plani yevmiye",
    "Kurumsal Yönetim ve İç Sistemler": "yonetim kurulu denetim komitesi ic sistem ic kontrol teftis ust yonetim politika",
    "Dış Hizmet Alımı": "destek hizmeti dis kaynak tedarikci hizmet saglayici dis hizmet",
    "Operasyonel Risk ve İş Sürekliliği": "is surekliligi operasyonel risk kayip felaket acil durum olay yonetimi kriz",
}


def _terms_of(s: str) -> list[str]:
    # çok kelimeli ifadeler korunur: "bilgi guvenligi", "is surekliligi" … tek kelimeler de ayrı terimdir
    words = s.split()
    phrases = {"bilgi guvenligi", "veri guvenligi", "kimlik dogrulama", "musteri tanima", "kisisel veri",
               "acik riza", "ilgili kisi", "veri sorumlusu", "finansal tablo", "hesap plani", "yonetim kurulu",
               "denetim komitesi", "ic sistem", "ic kontrol", "ust yonetim", "destek hizmeti", "dis kaynak",
               "hizmet saglayici", "dis hizmet", "is surekliligi", "operasyonel risk", "acil durum",
               "olay yonetimi", "elektronik para", "kredi komite", "uyum gorevlisi", "teror finansman"}
    out, i = [], 0
    while i < len(words):
        two = " ".join(words[i:i + 2])
        if two in phrases:
            out.append(two)
            i += 2
        else:
            out.append(words[i])
            i += 1
    return out


def alan_skorlari(filename: str, text: str) -> dict[str, float]:
    name, body = f" {processing.norm(filename)} ", f" {processing.norm(text[:60000])} "
    out = {}
    for alan, words in ALAN_SOZLUK.items():
        s = 0.0
        for term in _terms_of(words):
            pat = re.compile(r"\s" + re.escape(term))
            s += 6 * len(pat.findall(name)) + min(len(pat.findall(body)), 25)
        if s:
            out[alan] = s
    return out


_ORG = re.compile(r"organizasyon|teskilat|gorev tanim|yetki (tablosu|matrisi)|organizasyon semasi|is tanim")
_LISANS = re.compile(r"\b(coso|iso iec|iso \d{4,5}|cobit|pci dss|iia|ippf)\b")

_alan_index: dict = {"key": None, "ix": None, "alan": {}}


def _builtin_index(conn):
    rows = conn.execute("SELECT id, filename, stored_path, alanlar FROM documents WHERE yerlesik = 1").fetchall()
    key = tuple(r["id"] for r in rows)
    if _alan_index["key"] != key:
        docs = []
        for r in rows:
            p = Path(r["stored_path"])
            if p.exists():
                docs.append({"id": r["id"], "ad": r["filename"], "text": p.read_text(encoding="utf-8")})
        _alan_index.update(key=key, ix=retrieval.Index(docs),
                           alan={r["id"]: json.loads(r["alanlar"] or "[]") for r in rows})
    return _alan_index["ix"], _alan_index["alan"]


def suggest(conn, filename: str, text: str) -> tuple[str, list[str]]:
    """Yüklenen belge için (tür, alanlar) önerisi; kullanıcı onaylar. Model gerektirmez.
    Tür: dosya adı (ve organizasyon için içerikte yoğun görev/birim dili).
    Alan: alan sözlüğü (ad 6 kat ağırlıklı); hiç eşleşme yoksa açık kaynaklara benzerlik."""
    name = processing.norm(filename)
    head = processing.norm(text[:6000])
    esas_adi = "uygulama esas" in name or "prosedur" in name or "yonerge" in name
    if _LISANS.search(name):
        tur = "lisansli"
    elif not esas_adi and (_ORG.search(name) or len(_ORG.findall(head)) >= 3):
        tur = "organizasyon"
    else:
        tur = "esas"
    if tur == "organizasyon":
        return tur, []
    score = alan_skorlari(filename, text)
    if not score:
        ix, alan_of = _builtin_index(conn)
        if ix and ix.pieces:
            step = max(len(text) // 6, 1)
            for i in range(0, min(len(text), step * 6), step):
                for h in ix.search(text[i:i + 3000], k=6, budget=20000):
                    for a in alan_of.get(h["doc_id"], []):
                        score[a] = score.get(a, 0) + h["score"] / max(len(alan_of.get(h["doc_id"], [])), 1)
    if not score:
        return tur, []
    ranked = sorted(score.items(), key=lambda x: -x[1])
    top = ranked[0][1]
    return tur, [a for a, s in ranked[:2] if s >= top * 0.5]


def clean_alanlar(values) -> list[str]:
    known = alanlar()
    out = []
    for v in values or []:
        v = str(v).strip()
        if v and v in known and v not in out:
            out.append(v)
    return out


def doc_text(row) -> str:
    """documents satırının modelin okuyacağı metni."""
    from . import documents
    p = Path(row["stored_path"])
    if not p.exists():
        return ""
    if row["yerlesik"]:
        return p.read_text(encoding="utf-8")
    return documents.extract_text(p)

