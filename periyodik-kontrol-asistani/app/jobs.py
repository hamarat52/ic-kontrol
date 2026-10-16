"""Kontrol seti üretimini arka planda yürüten iş.

Üretim istemci bağlantısından bağımsızdır: sayfa yenilense ya da kapansa da devam
eder; ilerleme veritabanına yazılır, istemci yoklayarak (polling) okur.
Yerel model tek seferde tek iş yapabildiği için aynı anda yalnız bir üretim çalışır.
"""
import json
import threading
import traceback
from pathlib import Path

from . import llm, processing, skills, storage

_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}


class Busy(Exception):
    pass


def is_running() -> str | None:
    for sid, t in list(_running.items()):
        if t.is_alive():
            return sid
        _running.pop(sid, None)
    return None


def _cancelled(set_id: str) -> bool:
    with storage.db_session() as conn:
        r = conn.execute("SELECT iptal FROM control_sets WHERE id = ?", (set_id,)).fetchone()
    return bool(r and r["iptal"])


class _StopCheck:
    """Akış sırasında her satırda veritabanına gitmemek için en fazla saniyede bir bakar."""
    def __init__(self, set_id):
        self.set_id, self.last, self.value = set_id, 0.0, False

    def __call__(self):
        import time
        now = time.monotonic()
        if not self.value and now - self.last >= 1.0:
            self.last = now
            self.value = _cancelled(self.set_id)
        return self.value


def _update(set_id: str, **fields):
    for k in ("progress", "istatistik", "bosluklar"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    with storage.db_session() as conn:
        conn.execute(
            f"UPDATE control_sets SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), set_id),
        )


def pretty_title(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else "Kontrol seti"


def start(set_id: str, docs: list[tuple[str, str]]):
    """docs: [(belge_adi, metin)]. Meşgulse Busy fırlatır."""
    if not _lock.acquire(blocking=False):
        raise Busy()
    if is_running():
        _lock.release()
        raise Busy()
    t = threading.Thread(target=_run_safe, args=(set_id, docs), daemon=True, name=f"set-{set_id}")
    _running[set_id] = t
    t.start()
    _lock.release()


def _run_safe(set_id, docs):
    try:
        run(set_id, docs)
    except Exception as exc:  # beklenmeyen hata: set asılı kalmasın
        traceback.print_exc()
        _update(set_id, durum="hata", hata=f"Beklenmeyen hata: {exc}")


def run(set_id: str, docs: list[tuple[str, str]]):
    chunks = []
    for name, text in docs:
        chunks.extend(processing.split_document(text, name))
    total = len(chunks)
    stats = {"bolum": total, "islenen": 0, "basarisiz": 0, "tekrar": 0, "dogrulanamayan": 0}
    _update(set_id, progress={"i": 0, "toplam": total}, istatistik=stats)

    skills_text = skills.read_all_skills_text()
    titles: list[str] = []
    gaps: list[str] = []
    last_error = None
    cancelled = False

    for n, chunk in enumerate(chunks):
        if _cancelled(set_id):
            cancelled = True
            break
        _update(set_id, progress={"i": n, "toplam": total, "belge": chunk["belge"], "bolum": chunk["bolum"]})
        ctx = {k: chunk[k] for k in ("belge", "bolum", "index", "toplam")}
        failed = False
        for ev in llm.stream_control_set(chunk["text"], skills_text, ctx, should_stop=_StopCheck(set_id)):
            kind = ev["event"]
            if kind == "control":
                c = ev["control"]
                if processing.is_duplicate(c["kontrol_adi"], titles):
                    stats["tekrar"] += 1
                    continue
                verified = processing.verify_quote(c["kaynak"], chunk["text"])
                if verified is False:
                    stats["dogrulanamayan"] += 1
                titles.append(c["kontrol_adi"])
                with storage.db_session() as conn:
                    conn.execute(
                        """INSERT INTO suggestions (run_id, kontrol_adi, kategori, hat, siklik, risk, efor,
                               gerekce, dayanak, kaynak, kaynak_belge, kaynak_bolum, kaynak_dogrulandi)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (set_id, c["kontrol_adi"], c["kategori"], c["hat"], c["siklik"], c["risk"], c["efor"],
                         c["gerekce"], c["dayanak"], c["kaynak"], chunk["belge"], chunk["bolum"],
                         None if verified is None else int(verified)),
                    )
            elif kind == "gap":
                if ev["metin"] and not processing.is_duplicate(ev["metin"], gaps, threshold=0.8):
                    gaps.append(ev["metin"])
                    _update(set_id, bosluklar=gaps)
            elif kind == "error":
                failed = True
                last_error = ev["error"]
        if _cancelled(set_id):
            cancelled = True
            break
        stats["islenen"] += 1
        if failed:
            stats["basarisiz"] += 1
        _update(set_id, istatistik=stats, progress={"i": n + 1, "toplam": total})

    # Başlık ve özet
    if titles and not cancelled:
        _update(set_id, progress={"i": total, "toplam": total, "asama": "ozet"})
        meta = llm.summarize_set([d[0] for d in docs], [c["bolum"] for c in chunks], titles, gaps)
        if meta:
            _update(set_id, baslik=meta["baslik"], ozet=meta["ozet"])

    hata = None
    if stats["basarisiz"]:
        hata = f"{stats['basarisiz']}/{total} bölüm işlenemedi. Son hata: {last_error}"
    if cancelled:
        durum = "iptal"
        hata = f"Üretim durduruldu ({stats['islenen']}/{total} bölüm işlendi)."
    elif titles:
        durum = "hazir"
    else:
        durum = "hata"
        hata = hata or "Hiç kontrol üretilmedi."
    _update(set_id, durum=durum, hata=hata, istatistik=stats, bosluklar=gaps, progress=None)
    _running.pop(set_id, None)


def recover_interrupted():
    """Sunucu yeniden başladığında yarıda kalan setleri kapatır."""
    with storage.db_session() as conn:
        rows = conn.execute("""SELECT c.id, COUNT(s.id) AS n FROM control_sets c
                               LEFT JOIN suggestions s ON s.run_id = c.id
                               WHERE c.durum = 'uretiliyor' GROUP BY c.id""").fetchall()
        for r in rows:
            conn.execute(
                "UPDATE control_sets SET durum = ?, hata = ?, progress = NULL WHERE id = ?",
                ("hazir" if r["n"] else "hata", "Sunucu yeniden başlatıldı; üretim yarıda kaldı.", r["id"]),
            )
