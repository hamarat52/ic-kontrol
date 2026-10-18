"""Kararlardan kural çıkarma (arka planda).

Kullanıcı bir sette yeterince ret / düzeltme yaptığında (eşik: 3 incelenmemiş karar) model bu
kararlarda ortak bir örüntü arar; bulursa "onay bekleyen" bir kural önerir. Kayıtları tek tek
öğrenilenlere yazmayız (ders yaz, kayıt yazma); kullanıcı onaylamadan hiçbir kural modele gitmez.
Yerel model aynı anda tek iş yaptığı için set üretimi sürerken inceleme ertelenir.
"""
from __future__ import annotations

import json
import threading
import traceback

from . import jobs, llm, model_settings, skills, storage

THRESHOLD = 3
_lock = threading.Lock()


def pending_events(conn, set_id: str) -> list[dict]:
    """Setteki incelenmemiş ret (hâlâ reddedilmiş olanlar) ve düzeltme kayıtları."""
    return [dict(r) for r in conn.execute(
        """SELECT f.id, f.karar, f.not_metni, s.kontrol_adi, s.kategori, s.hat, s.siklik, s.sorumlu, s.status,
                  s.kaynak_belge
           FROM feedback f JOIN suggestions s ON s.id = f.suggestion_id
           WHERE s.run_id = ? AND f.incelendi = 0
             AND ((f.karar = 'red' AND s.status = 'red') OR f.karar = 'duzenle')
           ORDER BY f.id""", (set_id,))]


def analyze(set_id: str) -> int | None:
    """Eşik aşıldıysa kararları modele sorar; önerilen kuralın id'sini (ya da None) döner."""
    if jobs.is_running():
        return None
    with storage.db_session() as conn:
        events = pending_events(conn, set_id)
        if len(events) < THRESHOLD:
            return None
        s = conn.execute("SELECT baslik, kapsam FROM control_sets WHERE id = ?", (set_id,)).fetchone()
        accepted = [r["kontrol_adi"] for r in conn.execute(
            "SELECT kontrol_adi FROM suggestions WHERE run_id = ? AND status = 'kabul' ORDER BY id DESC LIMIT 10", (set_id,))]
    rejected = [e for e in events if e["karar"] == "red"]
    edits = [f"{e['kontrol_adi']}: {e['not_metni']}" for e in events if e["karar"] == "duzenle" and e["not_metni"]]
    result = llm.propose_rule(rejected, edits, accepted, conn=model_settings.active())
    kapsam = json.loads(s["kapsam"] or "{}") if s else {}
    with storage.db_session() as conn:
        q = ",".join("?" * len(events))
        conn.execute(f"UPDATE feedback SET incelendi = 1 WHERE id IN ({q})", [e["id"] for e in events])
        if not result:
            return None
        names = [e["kontrol_adi"] for e in rejected][:3]
        neden = []
        if rejected:
            neden.append(f"{len(rejected)} ret: " + "; ".join(f"“{n}”" for n in names)
                         + (f" ve {len(rejected) - len(names)} tane daha" if len(rejected) > len(names) else ""))
        if edits:
            neden.append(f"{len(edits)} düzeltme")
        if result.get("gerekce"):
            neden.append(result["gerekce"])
        kaynak = "ret" if rejected and not edits else "duzenleme" if edits and not rejected else "kararlar"
        cats = [e["kategori"] for e in events]
        alanlar = kapsam.get("alanlar") or skills.doc_alanlar(conn, [e["kaynak_belge"] for e in events if e.get("kaynak_belge")])
        topic = skills.guess_topic(max(set(cats), key=cats.count) if cats else "", alanlar)
        return skills.propose(conn, topic, result["kural"], kaynak, set_id, s["baslik"] if s else None,
                              " · ".join(neden))


def _run(set_id):
    if not _lock.acquire(blocking=False):
        return
    try:
        analyze(set_id)
    except Exception:
        traceback.print_exc()
    finally:
        _lock.release()


def maybe_analyze_async(set_id: str) -> None:
    with storage.db_session() as conn:
        if len(pending_events(conn, set_id)) < THRESHOLD:
            return
    threading.Thread(target=_run, args=(set_id,), daemon=True, name=f"ogrenme-{set_id}").start()
