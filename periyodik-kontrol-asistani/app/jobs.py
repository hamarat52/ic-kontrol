"""Kontrol seti üretimini arka planda yürüten iş.

Üretim istemci bağlantısından bağımsızdır: sayfa yenilense ya da kapansa da devam
eder; ilerleme veritabanına yazılır, istemci yoklayarak (polling) okur.
Yerel model tek seferde tek iş yapabildiği için aynı anda yalnız bir üretim çalışır.
"""
import json
import re
import threading
import traceback
from pathlib import Path

from . import llm, model_settings, processing, retrieval, skills, storage

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


def start(set_id: str, docs: list[tuple[str, str]], basis: list[dict] | None = None, org: list[dict] | None = None):
    """docs: [(belge_adi, metin)] — kontrol üretilecek uygulama esasları.
    basis: [{"id","ad","text"}] dayanak kaynakları (mevzuat/standart); org: organizasyon belgeleri.
    Meşgulse Busy fırlatır."""
    if not _lock.acquire(blocking=False):
        raise Busy()
    if is_running():
        _lock.release()
        raise Busy()
    t = threading.Thread(target=_run_safe, args=(set_id, docs, basis or [], org or []), daemon=True, name=f"set-{set_id}")
    _running[set_id] = t
    t.start()
    _lock.release()


def _run_safe(set_id, docs, basis, org):
    try:
        run(set_id, docs, basis, org)
    except Exception as exc:  # beklenmeyen hata: set asılı kalmasın
        traceback.print_exc()
        _update(set_id, durum="hata", hata=f"Beklenmeyen hata: {exc}")


RETRY_MIN_CHARS = 800   # bundan uzun bir bölüm boş dönerse bir kez daha sorulur
RETRY_HINT = ("UYARI: Bu bölüm için önceki denemede hiç kontrol çıkmadı. Bölümde onay, süre, "
              "limit, kayıt, bildirim veya inceleme içeren kurallar var; her biri için en az bir kontrol yaz.")


def _history() -> tuple[str, list[str]]:
    """Kurumun önceki kararları: (prompt'a eklenecek örnek metni, reddedilen başlıklar)."""
    with storage.db_session() as conn:
        acc = conn.execute("""SELECT kontrol_adi, kategori, hat, siklik FROM library
                              ORDER BY id DESC LIMIT 12""").fetchall()
        rej = [r["kontrol_adi"] for r in conn.execute(
            """SELECT kontrol_adi FROM suggestions WHERE status = 'red'
               GROUP BY kontrol_adi ORDER BY MAX(id) DESC LIMIT 40""")]
    if not acc and not rej:
        return "", rej
    lines = ["KURUMUN ÖNCEKİ KARARLARI:"]
    if acc:
        lines.append("Kabul edilen kontrollerden örnekler (ad, ayrıntı düzeyi ve sınıflandırma için örnek al):")
        lines += [f"- {r['kontrol_adi']} ({r['kategori']}, Hat {r['hat']}, {r['siklik']})" for r in acc]
    if rej:
        lines.append("Reddedilen kontroller (bunlara benzer kontrol ÖNERME):")
        lines += [f"- {t}" for t in rej[:20]]
    return "\n".join(lines), rej


BASIS_HEAD = ("DAYANAK ADAYLARI (yalnız \"dayanak\" ve \"dayanak_no\" alanları için; bunlardan kontrol "
              "üretme, ilgisizse kullanma):")
ORG_HEAD = "ŞİRKET ORGANİZASYONU (bu bölümle ilgili birim ve görev tanımları; \"sorumlu\" ve hat için):"


def _links(c: dict, hits: list[dict]) -> list[dict]:
    """Modelin dayanak_no ile işaret ettiği adayları (yoksa dayanak metnindeki madde numarasıyla
    eşleşenleri) tıklanabilir bağlantıya çevirir."""
    picked = [hits[n - 1] for n in c.get("dayanak_no") or [] if 1 <= n <= len(hits)]
    if not picked and c.get("dayanak"):
        nums = set(re.findall(r"(?:madde|m\.)\s*(\d+)", c["dayanak"], re.I))
        picked = [h for h in hits if (m := re.match(r"(?:Geçici |Ek )?Madde (\d+)", h["label"])) and m.group(1) in nums]
    out, seen = [], set()
    for h in picked:
        key = (h["doc_id"], h["label"])
        if key in seen:
            continue
        seen.add(key)
        body = re.sub(r"^\s*(?:(?:GEÇİCİ|Geçici|EK|Ek)\s+)?(?:MADDE|Madde)\s+\S+\s*[–—-]\s*", "", h["text"])
        out.append({"doc_id": h["doc_id"], "doc": h["doc"], "label": h["label"].replace(" (devam)", ""),
                    "alinti": " ".join(body.split()[:30])})
    return out


def run(set_id: str, docs: list[tuple[str, str]], basis: list[dict] | None = None, org: list[dict] | None = None):
    basis_ix = retrieval.Index(basis) if basis else None
    org_ix = retrieval.Index(org) if org else None
    chunks = []
    for name, text in docs:
        chunks.extend(processing.split_document(text, name))
    total = len(chunks)
    stats = {"bolum": total, "islenen": 0, "basarisiz": 0, "tekrar": 0, "dogrulanamayan": 0,
             "reddedilene_benzer": 0, "yeniden_denenen": 0}
    _update(set_id, progress={"i": 0, "toplam": total}, istatistik=stats)

    skills_text = skills.read_all_skills_text()
    examples, rejected = _history()
    llm_conn = model_settings.active()   # set boyunca aynı model (kullanıcı arada değiştirse de)
    titles: list[str] = []
    gaps: list[str] = []
    last_error = None
    cancelled = False

    def process(chunk, ctx, hint="") -> tuple[int, bool]:
        """Bir bölümü modele sorar; (modelin önerdiği kontrol sayısı, hata oldu mu) döner."""
        nonlocal last_error
        added, failed = 0, False
        hits = basis_ix.search(chunk["text"], k=5, budget=5000) if basis_ix else []
        org_hits = org_ix.search(chunk["text"], k=3, budget=2500) if org_ix else []
        for ev in llm.stream_control_set(chunk["text"], skills_text, ctx, should_stop=_StopCheck(set_id),
                                         examples=examples, hint=hint, conn=llm_conn,
                                         basis=retrieval.format_block(hits, BASIS_HEAD),
                                         org=retrieval.format_block(org_hits, ORG_HEAD)):
            kind = ev["event"]
            if kind == "control":
                c = ev["control"]
                added += 1
                if processing.is_duplicate(c["kontrol_adi"], titles):
                    stats["tekrar"] += 1
                    continue
                if processing.is_duplicate(c["kontrol_adi"], rejected):
                    stats["reddedilene_benzer"] += 1
                    continue
                verified = processing.verify_quote(c["kaynak"], chunk["text"])
                if verified is False:
                    stats["dogrulanamayan"] += 1
                titles.append(c["kontrol_adi"])
                links = _links(c, hits)
                if links:
                    stats["dayanakli"] = stats.get("dayanakli", 0) + 1
                dayanak = c["dayanak"] or "; ".join(f"{l['doc']} — {l['label']}" for l in links)
                with storage.db_session() as conn:
                    conn.execute(
                        """INSERT INTO suggestions (run_id, kontrol_adi, kategori, hat, siklik, risk, efor,
                               gerekce, dayanak, kaynak, kaynak_belge, kaynak_bolum, kaynak_dogrulandi,
                               sorumlu, dayanak_bag)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (set_id, c["kontrol_adi"], c["kategori"], c["hat"], c["siklik"], c["risk"], c["efor"],
                         c["gerekce"], dayanak, c["kaynak"], chunk["belge"], chunk["bolum"],
                         None if verified is None else int(verified), c.get("sorumlu") or None,
                         json.dumps(links, ensure_ascii=False) if links else None),
                    )
            elif kind == "gap":
                if ev["metin"] and not processing.is_duplicate(ev["metin"], gaps, threshold=0.8):
                    gaps.append(ev["metin"])
                    _update(set_id, bosluklar=gaps)
            elif kind == "error":
                failed = True
                last_error = ev["error"]
        return added, failed

    for n, chunk in enumerate(chunks):
        if _cancelled(set_id):
            cancelled = True
            break
        _update(set_id, progress={"i": n, "toplam": total, "belge": chunk["belge"], "bolum": chunk["bolum"]})
        ctx = {k: chunk[k] for k in ("belge", "bolum", "index", "toplam")}
        added, failed = process(chunk, ctx)
        if (not added and not failed and len(chunk["text"]) >= RETRY_MIN_CHARS
                and not _cancelled(set_id)):
            stats["yeniden_denenen"] += 1
            added, failed = process(chunk, ctx, hint=RETRY_HINT)
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
        meta = llm.summarize_set([d[0] for d in docs], [c["bolum"] for c in chunks], titles, gaps, conn=llm_conn)
        if meta:
            with storage.db_session() as conn:
                r = conn.execute("SELECT kapsam FROM control_sets WHERE id = ?", (set_id,)).fetchone()
            fixed = bool(r and r["kapsam"] and json.loads(r["kapsam"]).get("baslik_sabit"))
            if fixed:   # kullanıcının verdiği set adı korunur
                _update(set_id, ozet=meta["ozet"])
            else:
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
