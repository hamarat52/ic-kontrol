import hashlib
import json
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, documents, processing, exporters, jobs, llm, model_settings, ogrenme, skills, sources, storage

app = FastAPI(title="Periyodik Kontrol Asistanı")
storage.init_db()
skills.ensure_seed()
jobs.recover_interrupted()
with storage.db_session() as _c:
    sources.sync_builtin(_c)   # uygulamayla gelen mevzuat ve standartlar
    # Sınıflandırma gelmeden önce yüklenmiş belgeler için tür/alan önerisi (kullanıcı onaylar)
    for _r in _c.execute("SELECT id, filename, stored_path FROM documents WHERE yerlesik = 0 AND alanlar IS NULL").fetchall():
        _t = documents.extract_text(Path(_r["stored_path"])) if Path(_r["stored_path"]).exists() else ""
        _tur, _al = sources.suggest(_c, _r["filename"], _t) if _t.strip() else ("esas", [])
        _c.execute("UPDATE documents SET tur = ?, alanlar = ?, onerildi = 1 WHERE id = ?",
                   (_tur, json.dumps(_al, ensure_ascii=False), _r["id"]))

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/")
def index():
    # Arayüz güncellenince tarayıcı eski CSS/JS'yi tutmasın
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def static_revalidate(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ------------------------------------------------------------------ yardımcılar

def _row(r):
    return dict(r) if r else None


def _load_set(conn, set_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM control_sets WHERE id = ?", (set_id,)).fetchone()
    if not r:
        return None
    s = dict(r)
    for key in ("bosluklar", "belge_adlari"):
        try:
            s[key] = json.loads(s[key]) if s[key] else []
        except json.JSONDecodeError:
            s[key] = []
    for key in ("progress", "istatistik", "kapsam"):
        try:
            s[key] = json.loads(s[key]) if s[key] else None
        except json.JSONDecodeError:
            s[key] = None
    return s


def _controls(conn, set_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT s.*, EXISTS(SELECT 1 FROM feedback f WHERE f.suggestion_id = s.id
                               AND f.karar IN ('duzenle','sohbet','prompt')) AS edited
           FROM suggestions s WHERE s.run_id = ? ORDER BY s.id""",
        (set_id,),
    ).fetchall()
    return [_control_out(r) for r in rows]


def _control_out(r) -> dict:
    c = dict(r)
    try:
        c["dayanak_bag"] = json.loads(c.get("dayanak_bag") or "[]")
    except json.JSONDecodeError:
        c["dayanak_bag"] = []
    return c


def _sync_library(conn, control: dict):
    """Kabul edilmiş kontrolü kütüphaneye yazar/günceller; değilse kütüphaneden çıkarır."""
    if control["status"] == "kabul":
        conn.execute(
            """INSERT INTO library (suggestion_id, set_id, kontrol_adi, kategori, hat, siklik,
                                    risk, efor, gerekce, dayanak, sorumlu)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(suggestion_id) DO UPDATE SET
                 kontrol_adi=excluded.kontrol_adi, kategori=excluded.kategori, hat=excluded.hat,
                 siklik=excluded.siklik, risk=excluded.risk, efor=excluded.efor,
                 gerekce=excluded.gerekce, dayanak=excluded.dayanak, sorumlu=excluded.sorumlu""",
            (control["id"], control["run_id"], control["kontrol_adi"], control["kategori"],
             control["hat"], control["siklik"], control["risk"], control["efor"],
             control["gerekce"], control["dayanak"], control.get("sorumlu")),
        )
    else:
        conn.execute("DELETE FROM library WHERE suggestion_id = ?", (control["id"],))


def _apply_fields(conn, control: dict, fields: dict, karar: str) -> list[str]:
    """Alanları günceller, geçmişe yazar, kütüphaneyi senkronlar. Değişiklik listesini döner."""
    updates = {k: v for k, v in fields.items() if v != control.get(k)}
    if not updates:
        return []
    diffs = [f"{k}: {control.get(k) or '—'} → {v}" for k, v in updates.items()]
    conn.execute(
        f"UPDATE suggestions SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
        (*updates.values(), control["id"]),
    )
    conn.execute(
        "INSERT INTO feedback (suggestion_id, karar, not_metni) VALUES (?, ?, ?)",
        (control["id"], karar, "; ".join(diffs)),
    )
    control.update(updates)
    _sync_library(conn, control)
    return diffs


# ------------------------------------------------------------------ sağlık

@app.get("/api/health")
def health():
    conn = model_settings.active()
    models, err = model_settings.list_models(conn, timeout=3)
    return {"ok": True, "llm_ok": err is None, "llm_error": err, "llm_base_url": conn["base_url"],
            "llm_model": conn["model"], "baglanti": conn["ad"], "tur": conn.get("tur", "yerel"),
            "model_var": conn["model"] in models if models else None}


# ------------------------------------------------------------------ model ayarları

def _settings_view(probe: bool = True):
    data = model_settings.load()
    out = []
    for b in data["baglantilar"]:
        item = model_settings.public(b)
        if probe and (b.get("tur") != "bulut" or b.get("api_key")):
            item["modeller"], item["hata"] = model_settings.list_models(b)
        else:
            item["modeller"], item["hata"] = [], ("Anahtar girilmedi." if b.get("tur") == "bulut" else None)
        out.append(item)
    return {"baglantilar": out, "aktif": data["aktif"]}


@app.get("/api/models")
def get_models():
    return _settings_view()


class ConnectionIn(BaseModel):
    id: str | None = None
    ad: str | None = None
    tur: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    anahtari_sil: bool = False


@app.post("/api/models/connections")
def save_connection(body: ConnectionIn):
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Adres http:// ya da https:// ile başlamalı.")
    data = model_settings.load()
    if not body.id and not (body.ad and body.base_url):
        raise HTTPException(400, "Yeni bağlantı için ad ve adres gerekli.")
    if body.id and not any(b["id"] == body.id for b in data["baglantilar"]):
        raise HTTPException(404, "Bağlantı bulunamadı.")
    conn = model_settings.upsert_connection(data, body.model_dump())
    model_settings.save(data)
    view = _settings_view()
    return {**view, "id": conn["id"]}


@app.delete("/api/models/connections/{conn_id}")
def delete_connection(conn_id: str):
    data = model_settings.load()
    if conn_id in ("yerel",):
        raise HTTPException(400, "Yerel bağlantı silinemez.")
    if data["aktif"].get("baglanti") == conn_id:
        raise HTTPException(409, "Kullanımdaki bağlantı silinemez; önce başka bir model seçin.")
    data["baglantilar"] = [b for b in data["baglantilar"] if b["id"] != conn_id]
    model_settings.save(data)
    return _settings_view()


class ActiveIn(BaseModel):
    baglanti: str
    model: str


@app.post("/api/models/active")
def set_active(body: ActiveIn):
    data = model_settings.load()
    if not any(b["id"] == body.baglanti for b in data["baglantilar"]):
        raise HTTPException(404, "Bağlantı bulunamadı.")
    if not body.model.strip():
        raise HTTPException(400, "Model adı boş olamaz.")
    data["aktif"] = {"baglanti": body.baglanti, "model": body.model.strip()}
    model_settings.save(data)
    return _settings_view(probe=False)


# ------------------------------------------------------------------ belgeler

@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    name = file.filename or "belge"
    suffix = Path(name).suffix.lower()
    if suffix not in (".pdf", ".docx", ".xlsx", ".txt", ".md"):
        raise HTTPException(400, "Yalnız pdf, docx, xlsx, txt ve md dosyaları kabul edilir.")
    data = await file.read()
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    text, warning = documents.extract(dest)
    sha = hashlib.sha256(data).hexdigest()
    bolum = len(processing.split_document(text, name)) if text.strip() else 0
    with storage.db_session() as conn:
        tur, alanlar = sources.suggest(conn, name, text) if text.strip() else ("esas", [])
        cur = conn.execute(
            """INSERT INTO documents (filename, stored_path, text_excerpt, char_count, uyari, sha, bolum,
                                      tur, alanlar, onerildi) VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (name, str(dest), text[:2000], len(text.strip()), warning, sha, bolum,
             tur, json.dumps(alanlar, ensure_ascii=False)),
        )
        new_id = cur.lastrowid
    return next(d for d in list_documents() if d["id"] == new_id)


def _backfill_documents(conn):
    """Eski kayıtlarda eksik olan özet (hash) ve bölüm sayısını bir kez hesaplar."""
    for r in conn.execute("SELECT id, filename, stored_path FROM documents WHERE yerlesik = 0 AND (sha IS NULL OR bolum IS NULL)").fetchall():
        p = Path(r["stored_path"])
        if not p.exists():
            continue
        text, _ = documents.extract(p)
        conn.execute("UPDATE documents SET sha = ?, bolum = ? WHERE id = ?",
                     (hashlib.sha256(p.read_bytes()).hexdigest(),
                      len(processing.split_document(text, r["filename"])) if text.strip() else 0, r["id"]))


@app.get("/api/documents")
def list_documents():
    with storage.db_session() as conn:
        _backfill_documents(conn)
        rows = [dict(r) for r in conn.execute(
            """SELECT id, filename, char_count, uyari, uploaded_at, sha, bolum, tur, alanlar, onerildi,
                      yerlesik, kurum, kaynak_url FROM documents
               ORDER BY yerlesik, CASE WHEN yerlesik = 1 THEN id ELSE -id END""")]
        used: dict[str, int] = {}
        used_ids: dict[int, int] = {}
        for s in conn.execute("SELECT belge_adlari, kapsam FROM control_sets"):
            k = json.loads(s["kapsam"] or "{}")
            for n in set(json.loads(s["belge_adlari"] or "[]")) | set(k.get("organizasyon") or []):
                used[n] = used.get(n, 0) + 1
            for i in set(k.get("dayanak") or []):
                used_ids[i] = used_ids.get(i, 0) + 1
    first_by_sha: dict[str, dict] = {}
    for d in sorted(rows, key=lambda x: x["id"]):
        d["alanlar"] = json.loads(d["alanlar"] or "[]")
        d["tur"] = d["tur"] or "esas"
        d["kullanim"] = used_ids.get(d["id"], 0) if d["yerlesik"] else used.get(d["filename"], 0)
        prev = first_by_sha.get(d["sha"]) if d["sha"] else None
        d["kopya_of"] = prev["filename"] if prev else None
        if d["sha"] and not prev:
            first_by_sha[d["sha"]] = d
    return rows


MEDIA_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
               ".html": "text/html; charset=utf-8",
               ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _doc_row(doc_id: int):
    with storage.db_session() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row or not Path(row["stored_path"]).exists():
        raise HTTPException(404, "Belge bulunamadı.")
    return dict(row)


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int, indir: int = 0):
    """Orijinal dosya. indir=1: indirme; değilse tarayıcıda açılır (PDF/TXT)."""
    d = _doc_row(doc_id)
    p = Path(d["stored_path"])
    name = d["filename"]
    if d["yerlesik"] and d.get("orijinal_path") and Path(d["orijinal_path"]).exists():
        p = Path(d["orijinal_path"])   # mevzuat.gov.tr sayfası ya da standardın PDF'i
        name = f"{d['filename'][:120]}{p.suffix}"
    disp = _disposition(name)
    if not indir:
        disp = disp.replace("attachment;", "inline;", 1)
    return FileResponse(p, media_type=MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                        headers={"Content-Disposition": disp})


@app.get("/api/documents/{doc_id}/text")
def document_text(doc_id: int):
    """Modelin okuduğu metin, modelin gördüğü bölümlere ayrılmış hâlde."""
    d = _doc_row(doc_id)
    if d["yerlesik"]:
        from . import retrieval
        text, warning = Path(d["stored_path"]).read_text(encoding="utf-8"), None
        parts = [{"bolum": p["label"], "text": p["text"]} for p in retrieval.split_pieces(text)]
        inline = bool(d.get("orijinal_path")) and Path(d["orijinal_path"]).exists()
    else:
        text, warning = documents.extract(Path(d["stored_path"]))
        parts = [{"bolum": c["bolum"], "text": c["text"]}
                 for c in (processing.split_document(text, d["filename"]) if text.strip() else [])]
        inline = Path(d["stored_path"]).suffix.lower() in (".pdf", ".txt", ".md")
    return {"id": d["id"], "filename": d["filename"], "uyari": warning, "char_count": len(text.strip()),
            "uploaded_at": d["uploaded_at"], "inline": inline, "tur": d["tur"] or "esas",
            "yerlesik": d["yerlesik"], "kurum": d.get("kurum"), "kaynak_url": d.get("kaynak_url"),
            "bolumler": parts}


class DocumentEditIn(BaseModel):
    tur: str | None = None
    alanlar: list[str] | None = None


@app.patch("/api/documents/{doc_id}")
def edit_document(doc_id: int, body: DocumentEditIn):
    """Belgenin türünü ve alanlarını onaylar/değiştirir (önerilen değerler onaylanmış olur)."""
    d = _doc_row(doc_id)
    if d["yerlesik"]:
        raise HTTPException(400, "Uygulamayla gelen kaynaklar değiştirilemez.")
    tur = body.tur or d["tur"] or "esas"
    if tur not in sources.KULLANICI_TURLERI:
        raise HTTPException(400, "Geçersiz belge türü.")
    alanlar = sources.clean_alanlar(body.alanlar) if body.alanlar is not None else json.loads(d["alanlar"] or "[]")
    with storage.db_session() as conn:
        conn.execute("UPDATE documents SET tur = ?, alanlar = ?, onerildi = 0 WHERE id = ?",
                     (tur, json.dumps(alanlar, ensure_ascii=False), doc_id))
    return next(x for x in list_documents() if x["id"] == doc_id)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    with storage.db_session() as conn:
        row = conn.execute("SELECT stored_path, yerlesik FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Belge bulunamadı.")
        if row["yerlesik"]:
            raise HTTPException(400, "Uygulamayla gelen kaynaklar kaldırılamaz.")
        Path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return {"ok": True}


# ------------------------------------------------------------------ kontrol setleri

@app.get("/api/sets")
def list_sets():
    with storage.db_session() as conn:
        rows = conn.execute(
            """SELECT c.id, c.baslik, c.durum, c.created_at, c.kapsam,
                      COUNT(s.id) AS toplam,
                      SUM(s.status = 'kabul') AS kabul,
                      SUM(s.status = 'red') AS red
               FROM control_sets c LEFT JOIN suggestions s ON s.run_id = c.id
               GROUP BY c.id ORDER BY c.created_at DESC, c.rowid DESC"""
        ).fetchall()
    return [{**dict(r), "kapsam": json.loads(r["kapsam"] or "null"), "kabul": r["kabul"] or 0, "red": r["red"] or 0}
            for r in rows]


@app.get("/api/sets/{set_id}")
def get_set(set_id: str):
    with storage.db_session() as conn:
        s = _load_set(conn, set_id)
        if not s:
            raise HTTPException(404, "Kontrol seti bulunamadı.")
        s["controls"] = _controls(conn, set_id)
        s["messages"] = [_message(conn, m) for m in
                         conn.execute("SELECT * FROM set_messages WHERE set_id = ? ORDER BY id", (set_id,)).fetchall()]
    return s


@app.delete("/api/sets/{set_id}")
def delete_set(set_id: str):
    if jobs.is_running() == set_id:
        raise HTTPException(409, "Bu set şu an üretiliyor; önce durdurun.")
    with storage.db_session() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM suggestions WHERE run_id = ?", (set_id,))]
        if ids:
            q = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM feedback WHERE suggestion_id IN ({q})", ids)
        conn.execute("DELETE FROM suggestions WHERE run_id = ?", (set_id,))
        conn.execute("DELETE FROM set_messages WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM control_sets WHERE id = ?", (set_id,))
    return {"ok": True}


class SetIn(BaseModel):
    belgeler: list[int] | None = None      # kontrol üretilecek uygulama esasları; boşsa hepsi
    dayanaklar: list[int] | None = None    # dayanak olarak bakılacak mevzuat/standartlar
    organizasyon: bool = True              # organizasyon/görev tanımlarını bağlam olarak kullan
    alanlar: list[str] = []
    baslik: str | None = None


@app.post("/api/sets", status_code=202)
def create_set(body: SetIn | None = None):
    """Seçilen uygulama esaslarından yeni kontrol seti üretimini arka planda başlatır.
    İlerleme: GET /api/sets/{id}/progress"""
    body = body or SetIn()
    if jobs.is_running():
        raise HTTPException(409, "Şu an başka bir set üretiliyor. Bitmesini bekleyin ya da durdurun.")
    with storage.db_session() as conn:
        _backfill_documents(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY id").fetchall()]
    by_id = {r["id"]: r for r in rows}
    esas = [r for r in rows if not r["yerlesik"] and (r["tur"] or "esas") in sources.URETEN]
    if body.belgeler is not None:
        bad = [i for i in body.belgeler if i not in by_id or by_id[i] not in esas]
        if bad:
            raise HTTPException(400, "Seçilen belgelerden bazıları uygulama esası değil ya da artık yok.")
        esas = [by_id[i] for i in body.belgeler]
    if not esas:
        raise HTTPException(400, "Önce kontrol üretilecek en az bir uygulama esası seçin.")
    basis_rows = []
    for i in body.dayanaklar or []:
        r = by_id.get(i)
        if not r or (r["tur"] or "esas") not in sources.DAYANAK:
            raise HTTPException(400, "Dayanak olarak yalnız mevzuat ve standartlar seçilebilir.")
        basis_rows.append(r)
    org_rows = [r for r in rows if r["tur"] == "organizasyon"] if body.organizasyon else []

    docs, skipped, seen = [], [], set()
    for d in esas:
        if d["sha"] and d["sha"] in seen:
            continue   # aynı içerik ikinci kez yüklenmiş: bir kez işlenir
        if d["sha"]:
            seen.add(d["sha"])
        text = sources.doc_text(d)
        if text.strip():
            docs.append((d["filename"], text))
        else:
            skipped.append(d["filename"])
    if not docs:
        raise HTTPException(400, "Seçilen belgelerin hiçbirinden metin okunamadı.")
    basis = [{"id": r["id"], "ad": r["filename"], "text": t} for r in basis_rows if (t := sources.doc_text(r)).strip()]
    org = [{"id": r["id"], "ad": r["filename"], "text": t} for r in org_rows if (t := sources.doc_text(r)).strip()]

    set_id = uuid.uuid4().hex[:10]
    names = [n for n, _ in docs]
    baslik = (body.baslik or "").strip()[:80]
    provisional = baslik or (jobs.pretty_title(names[0]) if len(names) == 1 else f"{len(names)} belge")
    kapsam = {"alanlar": sources.clean_alanlar(body.alanlar), "dayanak": [b["id"] for b in basis],
              "dayanak_adlari": [b["ad"] for b in basis], "organizasyon": [o["ad"] for o in org],
              "baslik_sabit": bool(baslik)}
    with storage.db_session() as conn:
        conn.execute(
            """INSERT INTO control_sets (id, baslik, belge_adlari, model, durum, hata, kapsam)
               VALUES (?,?,?,?, 'uretiliyor', ?, ?)""",
            (set_id, provisional, json.dumps(names, ensure_ascii=False), model_settings.active()["model"],
             f"Metni okunamayan belgeler atlandı: {', '.join(skipped)}" if skipped else None,
             json.dumps(kapsam, ensure_ascii=False)),
        )
    try:
        jobs.start(set_id, docs, basis, org)
    except jobs.Busy:
        with storage.db_session() as conn:
            conn.execute("DELETE FROM control_sets WHERE id = ?", (set_id,))
        raise HTTPException(409, "Şu an başka bir set üretiliyor.")
    with storage.db_session() as conn:
        return _load_set(conn, set_id)


@app.get("/api/sets/{set_id}/progress")
def set_progress(set_id: str, after: int = 0):
    """Yoklama uç noktası: setin durumu + `after` id'sinden sonra eklenen kontroller."""
    with storage.db_session() as conn:
        s = _load_set(conn, set_id)
        if not s:
            raise HTTPException(404, "Kontrol seti bulunamadı.")
        rows = conn.execute(
            "SELECT *, 0 AS edited FROM suggestions WHERE run_id = ? AND id > ? ORDER BY id", (set_id, after)
        ).fetchall()
        s["controls"] = [_control_out(r) for r in rows]
        s["toplam_kontrol"] = conn.execute(
            "SELECT COUNT(*) FROM suggestions WHERE run_id = ?", (set_id,)).fetchone()[0]
    return s


@app.post("/api/sets/{set_id}/cancel")
def cancel_set(set_id: str):
    with storage.db_session() as conn:
        cur = conn.execute("UPDATE control_sets SET iptal = 1 WHERE id = ? AND durum = 'uretiliyor'", (set_id,))
    return {"ok": True, "cancelled": cur.rowcount > 0}


class ChatIn(BaseModel):
    message: str
    control_id: int | None = None


@app.post("/api/sets/{set_id}/chat")
def chat(set_id: str, body: ChatIn):
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Mesaj boş.")
    with storage.db_session() as conn:
        if not _load_set(conn, set_id):
            raise HTTPException(404, "Kontrol seti bulunamadı.")
        controls = _controls(conn, set_id)
        conn.execute("INSERT INTO set_messages (set_id, control_id, role, content) VALUES (?,?, 'user', ?)",
                     (set_id, body.control_id, msg))
    by_id = {c["id"]: c for c in controls}
    focus = by_id.get(body.control_id) if body.control_id else None

    with storage.db_session() as conn:
        sset = _load_set(conn, set_id)
    alanlar = (sset.get("kapsam") or {}).get("alanlar") or None
    result = llm.chat_feedback(controls, focus, msg, skills.read_skills_text(alanlar))
    if not result["ok"]:
        with storage.db_session() as conn:
            conn.execute("INSERT INTO set_messages (set_id, control_id, role, content) VALUES (?,?, 'ai', ?)",
                         (set_id, body.control_id, result["error"]))
        return {"ok": False, "error": result["error"]}

    changes = []
    with storage.db_session() as conn:
        for item in result["degisiklikler"]:
            try:
                cid = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            control = by_id.get(cid)
            if not control:
                continue
            before = dict(control)
            fields = llm.normalize_fields(item.get("alanlar") or {})
            diffs = _apply_fields(conn, control, fields, "sohbet")
            if diffs:
                changes.append({
                    "id": cid, "kontrol_adi": before["kontrol_adi"],
                    "alanlar": {k: [before.get(k), control[k]] for k in fields if before.get(k) != control[k]},
                })
        lids = []
        if result["dersler"]:
            # Dersler doğrudan yazılmaz: her biri ayrı, onay bekleyen öneri olur
            ref = focus or (by_id.get(changes[0]["id"]) if changes else None) or {}
            kategori = ref.get("kategori", "")
            konu_alan = alanlar or skills.doc_alanlar(conn, [ref["kaynak_belge"]] if ref.get("kaynak_belge") else [])
            for d in result["dersler"]:
                topic = "genel-cerceve" if d["genel"] else skills.guess_topic(kategori, konu_alan)
                lid = skills.propose(conn, topic, d["kural"], "sohbet", set_id, sset.get("baslik"), f"Senin mesajın: “{msg}”")
                if lid:
                    lids.append(lid)
        cur = conn.execute(
            """INSERT INTO set_messages (set_id, control_id, role, content, changes, lesson, learning_ids)
               VALUES (?,?, 'ai', ?,?,?,?)""",
            (set_id, body.control_id, result["yanit"], json.dumps(changes, ensure_ascii=False), result["ders"],
             json.dumps(lids) if lids else None),
        )
        ai_msg = _message(conn, conn.execute("SELECT * FROM set_messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        updated = _controls(conn, set_id)

    return {"ok": True, "message": ai_msg, "controls": updated}


def _message(conn, m) -> dict:
    d = {**dict(m), "changes": json.loads(m["changes"]) if m["changes"] else []}
    ids = json.loads(m["learning_ids"]) if m["learning_ids"] else ([m["learning_id"]] if m["learning_id"] else [])
    d["learnings"] = [dict(r) for i in ids
                      if (r := conn.execute("SELECT id, metin, durum, skill FROM learnings WHERE id = ?", (i,)).fetchone())]
    d["learning"] = d["learnings"][0] if d["learnings"] else None
    return d


# ------------------------------------------------------------------ tek kontrol

class DecisionIn(BaseModel):
    karar: str  # kabul | red | bekliyor


def _decide(control_id: int, karar: str) -> dict:
    with storage.db_session() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (control_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Kontrol bulunamadı.")
        control = dict(row)
        prev = control["status"]
        if prev == karar:
            return control
        conn.execute("UPDATE suggestions SET status = ? WHERE id = ?", (karar, control_id))
        conn.execute("INSERT INTO feedback (suggestion_id, karar) VALUES (?, ?)", (control_id, karar))
        control["status"] = karar
        _sync_library(conn, control)
    if karar == "red":
        # Ret tek başına kural değildir; benzer kararlar birikince model kural önerir (onaya gelir)
        ogrenme.maybe_analyze_async(control["run_id"])
    return control


@app.post("/api/controls/{control_id}/decision")
def decide(control_id: int, body: DecisionIn):
    if body.karar not in ("kabul", "red", "bekliyor"):
        raise HTTPException(400, "Geçersiz karar.")
    return {"ok": True, "control": _decide(control_id, body.karar)}


class BulkDecisionIn(BaseModel):
    ids: list[int]
    karar: str


@app.post("/api/controls/bulk-decision")
def bulk_decide(body: BulkDecisionIn):
    if body.karar not in ("kabul", "red", "bekliyor"):
        raise HTTPException(400, "Geçersiz karar.")
    if not body.ids or len(body.ids) > 500:
        raise HTTPException(400, "1–500 kontrol seçilmeli.")
    return {"ok": True, "controls": [_decide(i, body.karar) for i in dict.fromkeys(body.ids)]}


class EditIn(BaseModel):
    kontrol_adi: str | None = None
    kategori: str | None = None
    hat: str | None = None
    siklik: str | None = None
    risk: str | None = None
    efor: str | None = None
    gerekce: str | None = None
    dayanak: str | None = None
    sorumlu: str | None = None


@app.patch("/api/controls/{control_id}")
def edit_control(control_id: int, body: EditIn):
    with storage.db_session() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (control_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Kontrol bulunamadı.")
        control = dict(row)
        fields = {k: v.strip() for k, v in body.model_dump().items() if isinstance(v, str)}
        fields = {k: v for k, v in fields.items() if v or k in ("gerekce", "dayanak")}
        diffs = _apply_fields(conn, control, fields, "duzenle")
    if diffs:
        ogrenme.maybe_analyze_async(control["run_id"])
    control["edited"] = 1 if diffs else 0
    return {"ok": True, "changed": bool(diffs), "control": control}


@app.get("/api/controls/{control_id}/history")
def history(control_id: int):
    labels = {"kabul": "Kabul edildi", "red": "Reddedildi", "bekliyor": "Karar geri alındı",
              "duzenle": "Düzenlendi", "sohbet": "Sohbetle güncellendi", "prompt": "Geri bildirimle güncellendi"}
    with storage.db_session() as conn:
        c = conn.execute("SELECT created_at FROM suggestions WHERE id = ?", (control_id,)).fetchone()
        if not c:
            raise HTTPException(404, "Kontrol bulunamadı.")
        items = [{"t": c["created_at"], "text": "Model önerdi"}]
        for f in conn.execute("SELECT * FROM feedback WHERE suggestion_id = ? ORDER BY id", (control_id,)):
            text = labels.get(f["karar"], f["karar"])
            if f["not_metni"]:
                text += f" · {f['not_metni']}"
            items.append({"t": f["created_at"], "text": text})
    return items


# ------------------------------------------------------------------ kütüphane & bilgi tabanı

@app.get("/api/library")
def get_library():
    with storage.db_session() as conn:
        rows = conn.execute(
            """SELECT l.*, c.baslik AS set_baslik, s.kaynak, s.kaynak_belge, s.kaynak_bolum, s.kaynak_dogrulandi
               FROM library l
               LEFT JOIN control_sets c ON c.id = l.set_id
               LEFT JOIN suggestions s ON s.id = l.suggestion_id
               ORDER BY l.kategori, l.kontrol_adi"""
        ).fetchall()
    return [dict(r) for r in rows]


def _library_export():
    items = get_library()
    if not items:
        raise HTTPException(400, "Dışa aktarılacak kabul edilmiş kontrol yok.")
    from datetime import date
    meta = {"baslik": "Kontroller", "created_at": date.today().isoformat(),
            "ozet": f"Kabul edilmiş {len(items)} kontrol, {len({i['set_id'] for i in items})} kontrol setinden derlenmiştir.",
            "belge_adlari": sorted({i["kaynak_belge"] for i in items if i.get("kaynak_belge")})}
    return meta, items


@app.get("/api/library/export/word")
def library_word():
    meta, items = _library_export()
    return StreamingResponse(exporters.build_word(meta, items, library=True),
                             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": _disposition(f"Kontroller {meta['created_at']}.docx")})


@app.get("/api/library/export/excel")
def library_excel():
    meta, items = _library_export()
    return StreamingResponse(exporters.build_excel(meta, items, library=True),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": _disposition(f"Kontroller {meta['created_at']}.xlsx")})


@app.delete("/api/library/{item_id}")
def remove_library(item_id: int):
    with storage.db_session() as conn:
        row = conn.execute("SELECT suggestion_id FROM library WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Kayıt bulunamadı.")
        conn.execute("DELETE FROM library WHERE id = ?", (item_id,))
        if row["suggestion_id"]:
            conn.execute("UPDATE suggestions SET status = 'bekliyor' WHERE id = ? AND status = 'kabul'",
                         (row["suggestion_id"],))
    return {"ok": True}


@app.get("/api/learnings")
def get_learnings():
    with storage.db_session() as conn:
        return skills.overview(conn)


class LearningDecisionIn(BaseModel):
    karar: str                 # onayla | at
    skill: str | None = None
    metin: str | None = None


@app.post("/api/learnings/{lid}/decision")
def decide_learning(lid: int, body: LearningDecisionIn):
    if body.karar not in ("onayla", "at"):
        raise HTTPException(400, "Geçersiz karar.")
    with storage.db_session() as conn:
        row = conn.execute("SELECT durum FROM learnings WHERE id = ?", (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "Kural bulunamadı.")
        if row["durum"] != "bekliyor":
            raise HTTPException(409, "Bu öneri zaten karara bağlanmış.")
        try:
            r = skills.decide(conn, lid, body.karar, body.skill, body.metin)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "learning": r}


class TextIn(BaseModel):
    metin: str


@app.patch("/api/learnings/{lid}")
def edit_learning(lid: int, body: TextIn):
    with storage.db_session() as conn:
        if not skills.edit(conn, lid, body.metin):
            raise HTTPException(400, "Kural bulunamadı ya da yeni metin boş.")
    return {"ok": True}


@app.delete("/api/learnings/{lid}")
def archive_learning(lid: int):
    with storage.db_session() as conn:
        if not skills.archive(conn, lid):
            raise HTTPException(404, "Kural bulunamadı.")
    return {"ok": True}


@app.post("/api/learnings")
def add_learning(body: LearningDecisionIn):
    """Kullanıcının elle eklediği kural (doğrudan onaylı)."""
    with storage.db_session() as conn:
        if (body.skill or "") not in skills.topics(conn):
            raise HTTPException(400, "Konu bulunamadı.")
        lid = skills.propose(conn, body.skill, body.metin or "", "elle")
        if not lid:
            raise HTTPException(400, "Kural boş ya da zaten var.")
        skills.decide(conn, lid, "onayla")
    return {"ok": True, "id": lid}


@app.get("/api/learnings/export")
def export_learnings(baslangic: int = 1):
    from datetime import date
    with storage.db_session() as conn:
        data = skills.export_zip(conn, with_seed=bool(baslangic))
    name = f"ic-kontrol-ogrenilenler-{date.today().isoformat()}.zip"
    return StreamingResponse(iter([data]), media_type="application/zip",
                             headers={"Content-Disposition": _disposition(name)})


@app.post("/api/prefs")
def add_pref(body: TextIn):
    with storage.db_session() as conn:
        try:
            pid = skills.add_pref(conn, body.metin)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "id": pid}


@app.patch("/api/prefs/{pid}")
def edit_pref(pid: int, body: TextIn):
    with storage.db_session() as conn:
        if not conn.execute("SELECT 1 FROM tercihler WHERE id = ? AND arsiv = 0", (pid,)).fetchone():
            raise HTTPException(404, "Tercih bulunamadı.")
        try:
            skills.edit_pref(conn, pid, body.metin)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/prefs/{pid}")
def delete_pref(pid: int):
    with storage.db_session() as conn:
        skills.delete_pref(conn, pid)
    return {"ok": True}


@app.get("/api/meta")
def meta():
    m = sources.manifest()
    return {"kategoriler": llm.KATEGORILER, "sikliklar": llm.SIKLIKLAR,
            "riskler": llm.RISKLER, "eforlar": llm.EFORLAR,
            "alanlar": [{"ad": a, "ikon": sources.ALAN_IKON.get(a, "📁")} for a in sources.alanlar()],
            "turler": sources.TURLER, "eklenemeyenler": m.get("lisansli_eklenemeyenler", [])}


# ------------------------------------------------------------------ dışa aktarma

def _export_data(set_id: str):
    with storage.db_session() as conn:
        s = _load_set(conn, set_id)
        if not s:
            raise HTTPException(404, "Kontrol seti bulunamadı.")
        controls = [c for c in _controls(conn, set_id) if c["status"] != "red"]
    if not controls:
        raise HTTPException(400, "Dışa aktarılacak kontrol yok.")
    return s, controls


def _fname(s: dict, ext: str) -> str:
    base = (s.get("baslik") or "kontrol-seti").strip()
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "-" for ch in base).strip().replace(" ", "-")
    return f"{safe or 'kontrol-seti'}.{ext}"


def _disposition(name: str) -> str:
    from urllib.parse import quote
    ascii_name = name.encode("ascii", "ignore").decode() or f"kontrol-seti{Path(name).suffix}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@app.get("/api/export/word")
def export_word(set_id: str):
    s, controls = _export_data(set_id)
    return StreamingResponse(
        exporters.build_word(s, controls),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _disposition(_fname(s, "docx"))},
    )


@app.get("/api/export/excel")
def export_excel(set_id: str):
    s, controls = _export_data(set_id)
    return StreamingResponse(
        exporters.build_excel(s, controls),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _disposition(_fname(s, "xlsx"))},
    )
