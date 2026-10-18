"""Öğrenen yapı: konular (skill), öğrenilen kurallar, kullanıcı tercihleri (USER.md).

Hermes / agentskills.io düzeni:
- Her konu bir klasör: <ad>/SKILL.md (YAML ön bilgisi: name, description, metadata).
- Başlangıç bilgisi app/seed_skills/<ad>/SKILL.md (sürüm kontrollü, kuruma özel veri içermez).
- Kurumun öğrendikleri veritabanındaki `learnings` tablosunda, kaynak ve onay bilgisiyle tutulur.
  Model bir kural önerir → "bekliyor"; kullanıcı onaylarsa "onayli" olur ve modele verilir.
- Her değişiklikten sonra data/skills/<ad>/SKILL.md ve data/USER.md yeniden yazılır; böylece
  aynı sunucudaki başka bir agent dosyaları doğrudan okuyabilir, zip ile de dışa aktarılır.
- Prompt'a yalnız setin alanlarıyla ilgili konular girer (alanlar boşsa konu her yerde geçerli).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import config, processing, storage

SEED_DIR = Path(__file__).resolve().parent / "seed_skills"
PREF_BUDGET = 1500          # tercihler (USER.md) için karakter sınırı
LEARN_BUDGET = 2500         # bir konunun öğrenilenleri için karakter sınırı (prompt şişmesin)


# ------------------------------------------------------------------ SKILL.md okuma / yazma

def _parse(text: str) -> tuple[dict, str]:
    """Basit YAML ön bilgisi ayrıştırıcı (yalnız bizim yazdığımız biçim)."""
    meta: dict = {"alanlar": []}
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return meta, text
    for line in m.group(1).split("\n"):
        k, _, v = line.strip().partition(":")
        v = v.strip()
        if k in ("name", "description", "baslik"):
            meta[k] = v
        elif k == "ikon":
            meta[k] = json.loads(v) if v.startswith('"') else v
        elif k == "alanlar":
            meta[k] = json.loads(v) if v.startswith("[") else []
    body = m.group(2).strip()
    body = re.sub(r"^# .*\n+", "", body)                        # başlık satırı ön bilgiden gelir
    body = body.split("\n## Öğrenilenler")[0].rstrip()
    return meta, body


def _frontmatter(t: dict) -> str:
    return "\n".join([
        "---", f"name: {t['name']}", f"description: {t['description']}", "metadata:", "  ic_kontrol:",
        f"    baslik: {t['baslik']}", f"    ikon: {json.dumps(t['ikon'], ensure_ascii=False)}",
        f"    alanlar: {json.dumps(t['alanlar'], ensure_ascii=False)}", "---", ""])


def slug(text: str) -> str:
    return processing.norm(text).replace(" ", "-")[:60] or "konu"


def _seed_topics() -> dict[str, dict]:
    out = {}
    for f in sorted(SEED_DIR.glob("*/SKILL.md")):
        meta, body = _parse(f.read_text(encoding="utf-8"))
        name = meta.get("name") or f.parent.name
        out[name] = {"name": name, "baslik": meta.get("baslik") or name, "ikon": meta.get("ikon") or "💡",
                     "description": meta.get("description") or "", "alanlar": meta.get("alanlar") or [],
                     "seed": body}
    return out


def _alan_topic(alan: str) -> dict:
    from .sources import ALAN_IKON
    return {"name": slug(alan), "baslik": alan, "ikon": ALAN_IKON.get(alan, "📁"),
            "description": f"{alan} alanında periyodik iç kontrol tasarlarken kullan; kurumun onayladığı kurallar.",
            "alanlar": [alan], "seed": ""}


def topics(conn=None) -> dict[str, dict]:
    """Bütün konular: başlangıç konuları + öğrenilen kuralı olan alan konuları."""
    from .sources import alanlar as alan_listesi
    out = _seed_topics()
    by_alan = {t["alanlar"][0]: n for n, t in out.items() if len(t["alanlar"]) == 1}
    for a in alan_listesi():
        if a not in by_alan:
            t = _alan_topic(a)
            out.setdefault(t["name"], t)
    return out


def topic_for_alan(alan: str | None) -> str:
    """Bir alana ait kuralların gideceği konu (ör. AML / Uyum → masak-aml)."""
    if not alan:
        return "kontrol-metrikleri"
    for n, t in topics().items():
        if t["alanlar"] == [alan]:
            return n
    return slug(alan)


def doc_alanlar(conn, belge_adlari: list[str]) -> list[str]:
    """Kontrollerin kaynak belgelerinin alanları (en sık görülen önce). Alan seçilmeden üretilmiş
    eski setlerde kuralın hangi konuya gideceğini belirlemek için."""
    from collections import Counter
    c: Counter = Counter()
    for n in belge_adlari:
        r = conn.execute("SELECT alanlar FROM documents WHERE filename = ? AND yerlesik = 0 ORDER BY id DESC", (n,)).fetchone()
        for a in json.loads(r["alanlar"] or "[]") if r else []:
            c[a] += 1
    return [a for a, _ in c.most_common()]


def guess_topic(kategori: str = "", alanlar: list[str] | None = None) -> str:
    if alanlar:
        return topic_for_alan(alanlar[0])
    k = (kategori or "").lower()
    if "aml" in k or "masak" in k or "şüpheli" in k:
        return "masak-aml"
    return "kontrol-metrikleri"


# ------------------------------------------------------------------ veri

def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def approved(conn, name: str) -> list[dict]:
    return _rows(conn, "SELECT * FROM learnings WHERE skill = ? AND durum = 'onayli' ORDER BY id", (name,))


def prefs(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM tercihler WHERE arsiv = 0 ORDER BY id")


def render_skill(t: dict, learned: list[dict], with_seed: bool = True) -> str:
    parts = [_frontmatter(t), f"# {t['baslik']}", ""]
    if with_seed and t["seed"]:
        parts += [t["seed"], ""]
    parts.append("## Öğrenilenler")
    if learned:
        parts += [f"- {l['metin']}" for l in learned]
    else:
        parts.append("_(henüz onaylanmış kural yok)_")
    return "\n".join(parts) + "\n"


def render_user(rows: list[dict]) -> str:
    lines = ["# USER.md — kullanıcı tercihleri", "",
             "Periyodik Kontrol Asistanı kullanıcısının çalışma tercihleri. Kontrol önerirken uygula.", ""]
    lines += [f"- {r['metin']}" for r in rows] or ["_(henüz tercih yok)_"]
    return "\n".join(lines) + "\n"


def write_files(conn) -> None:
    """data/skills/<ad>/SKILL.md ve data/USER.md dosyalarını veritabanından yeniden yazar."""
    root = Path(config.SKILLS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    for name, t in topics(conn).items():
        learned = approved(conn, name)
        if not t["seed"] and not learned:
            continue
        d = root / name
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(render_skill(t, learned), encoding="utf-8")
    (Path(config.DATA_DIR) / "USER.md").write_text(render_user(prefs(conn)), encoding="utf-8")


def _utc_now() -> str:
    """Veritabanındaki tüm zamanlar UTC (SQLite datetime('now') ile aynı); arayüz yerel saate çevirir."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_to_utc(s: str) -> str:
    """Eski dosyalardaki yerel saat damgası ('2026-10-16 21:23' ya da '2026-10-16') → UTC."""
    fmt = "%Y-%m-%d %H:%M" if len(s) > 10 else "%Y-%m-%d"
    return datetime.strptime(s, fmt).astimezone().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_ENTRY = re.compile(r"^- \[(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\]\s*(.+)$")


def ensure_seed() -> None:
    """Eski düz dosya düzenini (data/skills/<ad>.md) bir kez taşır ve dosyaları yazar.
    Eski 'Reddedildi: …' ve 'Kullanıcı düzeltti — …' satırları kural değil kayıttır: arşive alınır."""
    root = Path(config.SKILLS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    with storage.db_session() as conn:
        old = sorted(root.glob("*.md"))
        if old:
            eski = root / "_eski"
            eski.mkdir(exist_ok=True)
            for f in old:
                for line in f.read_text(encoding="utf-8").split("\n"):
                    m = _ENTRY.match(line.strip())
                    if not m:
                        continue
                    text = m.group(2).strip()
                    kayit = text.startswith(("Reddedildi:", "Kullanıcı düzeltti"))
                    conn.execute("""INSERT INTO learnings (skill, metin, durum, kaynak, created_at, decided_at)
                                    VALUES (?,?,?,?,?,?)""",
                                 (f.stem, text, "arsiv" if kayit else "onayli", "ret" if kayit else "eski",
                                  _local_to_utc(m.group(1)), _utc_now()))
                shutil.move(str(f), eski / f.name)
        write_files(conn)


# ------------------------------------------------------------------ prompt metni

def read_skills_text(alanlar: list[str] | None = None) -> str:
    """Prompt için: ilgili konular (başlangıç bilgisi + onaylı kurallar) ve kullanıcı tercihleri.
    alanlar verilirse yalnız o alanların konuları ve her yerde geçerli konular girer."""
    want = set(alanlar or [])
    parts = []
    with storage.db_session() as conn:
        for name, t in topics(conn).items():
            if want and t["alanlar"] and not (set(t["alanlar"]) & want):
                continue
            learned = approved(conn, name)
            if not t["seed"] and not learned:
                continue
            text = f"## Konu: {t['baslik']}\n{t['seed']}".rstrip()
            if learned:
                rules, used = [], 0
                for l in reversed(learned):                       # en yeniler öncelikli
                    if used + len(l["metin"]) > LEARN_BUDGET:
                        break
                    rules.insert(0, f"- {l['metin']}")
                    used += len(l["metin"])
                text += "\n### Kurumun onayladığı kurallar (uygula)\n" + "\n".join(rules)
            parts.append(text)
        p = prefs(conn)
    if p:
        parts.append("## Kullanıcı tercihleri (USER.md — uygula)\n" + "\n".join(f"- {r['metin']}" for r in p))
    return "\n\n".join(parts)


def read_all_skills_text() -> str:   # geriye dönük uyum
    return read_skills_text(None)


def used_topics(alanlar: list[str] | None) -> list[str]:
    want = set(alanlar or [])
    return [n for n, t in topics().items() if not (want and t["alanlar"] and not (set(t["alanlar"]) & want))]


# ------------------------------------------------------------------ öneriler ve onay

def propose(conn, skill: str, metin: str, kaynak: str, set_id: str | None = None,
            set_baslik: str | None = None, neden: str | None = None) -> int | None:
    metin = " ".join((metin or "").split())
    if not metin:
        return None
    # aynı (ya da çok benzer) kural zaten onaylı ya da bekliyorsa yenisini açma
    for r in conn.execute("SELECT metin FROM learnings WHERE durum IN ('onayli','bekliyor')"):
        if processing.similarity(r["metin"], metin) >= 0.85:
            return None
    cur = conn.execute("""INSERT INTO learnings (skill, metin, durum, kaynak, set_id, set_baslik, neden)
                          VALUES (?,?, 'bekliyor', ?,?,?,?)""", (skill, metin, kaynak, set_id, set_baslik, neden))
    return cur.lastrowid


def decide(conn, lid: int, karar: str, skill: str | None = None, metin: str | None = None) -> dict | None:
    """karar: onayla | at. Onaylarken konu ve metin değiştirilebilir."""
    row = conn.execute("SELECT * FROM learnings WHERE id = ?", (lid,)).fetchone()
    if not row:
        return None
    now = _utc_now()
    if karar == "onayla":
        name = skill or row["skill"]
        if name not in topics(conn):
            raise ValueError("Konu bulunamadı.")
        text = " ".join((metin or row["metin"]).split())
        if not text:
            raise ValueError("Kural boş olamaz.")
        conn.execute("UPDATE learnings SET durum='onayli', skill=?, metin=?, decided_at=? WHERE id=?",
                     (name, text, now, lid))
    else:
        conn.execute("UPDATE learnings SET durum='atildi', decided_at=? WHERE id=?", (now, lid))
    write_files(conn)
    return dict(conn.execute("SELECT * FROM learnings WHERE id = ?", (lid,)).fetchone())


def edit(conn, lid: int, metin: str) -> bool:
    text = " ".join((metin or "").split())
    if not text:
        return False
    cur = conn.execute("UPDATE learnings SET metin = ? WHERE id = ? AND durum = 'onayli'", (text, lid))
    write_files(conn)
    return cur.rowcount > 0


def archive(conn, lid: int) -> bool:
    cur = conn.execute("UPDATE learnings SET durum = 'arsiv', decided_at = datetime('now') WHERE id = ? AND durum = 'onayli'",
                       (lid,))
    write_files(conn)
    return cur.rowcount > 0


# ------------------------------------------------------------------ tercihler (USER.md)

def pref_total(conn, skip_id: int | None = None) -> int:
    return sum(len(r["metin"]) for r in prefs(conn) if r["id"] != skip_id)


def add_pref(conn, metin: str) -> int:
    text = " ".join((metin or "").split())
    if not text:
        raise ValueError("Tercih boş olamaz.")
    if pref_total(conn) + len(text) > PREF_BUDGET:
        raise ValueError(f"Tercihler en fazla {PREF_BUDGET} karakter olabilir; önce birini kısalt ya da sil.")
    cur = conn.execute("INSERT INTO tercihler (metin) VALUES (?)", (text,))
    write_files(conn)
    return cur.lastrowid


def edit_pref(conn, pid: int, metin: str) -> None:
    text = " ".join((metin or "").split())
    if not text:
        raise ValueError("Tercih boş olamaz.")
    if pref_total(conn, skip_id=pid) + len(text) > PREF_BUDGET:
        raise ValueError(f"Tercihler en fazla {PREF_BUDGET} karakter olabilir.")
    conn.execute("UPDATE tercihler SET metin = ? WHERE id = ?", (text, pid))
    write_files(conn)


def delete_pref(conn, pid: int) -> None:
    conn.execute("UPDATE tercihler SET arsiv = 1 WHERE id = ?", (pid,))
    write_files(conn)


# ------------------------------------------------------------------ sayfa verisi ve dışa aktarma

def overview(conn) -> dict:
    usage = {r["skill"]: r["n"] for r in conn.execute(
        """SELECT skill, COUNT(DISTINCT set_id) AS n FROM skill_usage
           WHERE created_at >= datetime('now', '-30 days') GROUP BY skill""")}
    items = []
    for name, t in topics(conn).items():
        learned = approved(conn, name)
        if not t["seed"] and not learned:
            continue
        items.append({**t, "learnings": learned, "kullanim_30": usage.get(name, 0)})
    pend = _rows(conn, "SELECT * FROM learnings WHERE durum = 'bekliyor' ORDER BY id DESC")
    all_topics = [{"name": n, "baslik": t["baslik"], "ikon": t["ikon"]} for n, t in topics(conn).items()]
    p = prefs(conn)
    return {"konular": items, "bekleyen": pend, "tercihler": p, "tercih_karakter": sum(len(r["metin"]) for r in p),
            "tercih_sinir": PREF_BUDGET, "tum_konular": all_topics}


README = """# Periyodik Kontrol Asistanı — öğrenilenler

Bu zip, uygulamanın kurumdan öğrendiklerini agentskills.io / Hermes skill biçiminde içerir.

- `<konu>/SKILL.md` — her konu bir skill: ön bilgi (name, description) + başlangıç bilgisi +
  kurumun onayladığı kurallar ("Öğrenilenler").
- `USER.md` — kullanıcının çalışma tercihleri.

Hermes'te kullanmak için: konu klasörlerini `~/.hermes/skills/` (ya da profilin skills klasörü)
altına kopyala; USER.md içeriğini kullanıcı profiline ekle. Başka bir agent için: SKILL.md
dosyalarını o agent'ın skill/talimat klasörüne koy.
"""


def export_zip(conn, with_seed: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, t in topics(conn).items():
            learned = approved(conn, name)
            if not learned and not (with_seed and t["seed"]):
                continue
            z.writestr(f"{name}/SKILL.md", render_skill(t, learned, with_seed=with_seed))
        z.writestr("USER.md", render_user(prefs(conn)))
        z.writestr("BENIOKU.md", README)
    return buf.getvalue()


def record_usage(conn, set_id: str, names: list[str]) -> None:
    conn.executemany("INSERT INTO skill_usage (set_id, skill) VALUES (?, ?)", [(set_id, n) for n in names])
