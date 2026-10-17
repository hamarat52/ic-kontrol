import hashlib
import json
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, documents, processing, exporters, jobs, llm, model_settings, skills, storage

app = FastAPI(title="Periyodik Kontrol Asistanı")
storage.init_db()
skills.ensure_seed()
jobs.recover_interrupted()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


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
    for key in ("progress", "istatistik"):
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
    return [dict(r) for r in rows]


def _sync_library(conn, control: dict):
    """Kabul edilmiş kontrolü kütüphaneye yazar/günceller; değilse kütüphaneden çıkarır."""
    if control["status"] == "kabul":
        conn.execute(
            """INSERT INTO library (suggestion_id, set_id, kontrol_adi, kategori, hat, siklik,
                                    risk, efor, gerekce, dayanak)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(suggestion_id) DO UPDATE SET
                 kontrol_adi=excluded.kontrol_adi, kategori=excluded.kategori, hat=excluded.hat,
                 siklik=excluded.siklik, risk=excluded.risk, efor=excluded.efor,
                 gerekce=excluded.gerekce, dayanak=excluded.dayanak""",
            (control["id"], control["run_id"], control["kontrol_adi"], control["kategori"],
             control["hat"], control["siklik"], control["risk"], control["efor"],
             control["gerekce"], control["dayanak"]),
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
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Yalnız pdf, docx, txt ve md dosyaları kabul edilir.")
    data = await file.read()
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    text, warning = documents.extract(dest)
    sha = hashlib.sha256(data).hexdigest()
    bolum = len(processing.split_document(text, name)) if text.strip() else 0
    with storage.db_session() as conn:
        conn.execute(
            "INSERT INTO documents (filename, stored_path, text_excerpt, char_count, uyari, sha, bolum) VALUES (?,?,?,?,?,?,?)",
            (name, str(dest), text[:2000], len(text.strip()), warning, sha, bolum),
        )
    return next(d for d in list_documents() if d["sha"] == sha and d["filename"] == name)


def _backfill_documents(conn):
    """Eski kayıtlarda eksik olan özet (hash) ve bölüm sayısını bir kez hesaplar."""
    for r in conn.execute("SELECT id, filename, stored_path FROM documents WHERE sha IS NULL OR bolum IS NULL").fetchall():
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
            "SELECT id, filename, char_count, uyari, uploaded_at, sha, bolum FROM documents ORDER BY id DESC")]
        used: dict[str, int] = {}
        for s in conn.execute("SELECT belge_adlari FROM control_sets"):
            for n in set(json.loads(s["belge_adlari"] or "[]")):
                used[n] = used.get(n, 0) + 1
    first_by_sha: dict[str, dict] = {}
    for d in sorted(rows, key=lambda x: x["id"]):
        d["kullanim"] = used.get(d["filename"], 0)
        prev = first_by_sha.get(d["sha"]) if d["sha"] else None
        d["kopya_of"] = prev["filename"] if prev else None
        if d["sha"] and not prev:
            first_by_sha[d["sha"]] = d
    return rows


MEDIA_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
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
    disp = _disposition(d["filename"])
    if not indir:
        disp = disp.replace("attachment;", "inline;", 1)
    return FileResponse(p, media_type=MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                        headers={"Content-Disposition": disp})


@app.get("/api/documents/{doc_id}/text")
def document_text(doc_id: int):
    """Modelin okuduğu metin, modelin gördüğü bölümlere ayrılmış hâlde."""
    d = _doc_row(doc_id)
    text, warning = documents.extract(Path(d["stored_path"]))
    chunks = processing.split_document(text, d["filename"]) if text.strip() else []
    return {"id": d["id"], "filename": d["filename"], "uyari": warning, "char_count": len(text.strip()),
            "uploaded_at": d["uploaded_at"], "inline": Path(d["stored_path"]).suffix.lower() in (".pdf", ".txt", ".md"),
            "bolumler": [{"bolum": c["bolum"], "text": c["text"]} for c in chunks]}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    with storage.db_session() as conn:
        row = conn.execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Belge bulunamadı.")
        Path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return {"ok": True}


# ------------------------------------------------------------------ kontrol setleri

@app.get("/api/sets")
def list_sets():
    with storage.db_session() as conn:
        rows = conn.execute(
            """SELECT c.id, c.baslik, c.durum, c.created_at,
                      COUNT(s.id) AS toplam,
                      SUM(s.status = 'kabul') AS kabul,
                      SUM(s.status = 'red') AS red
               FROM control_sets c LEFT JOIN suggestions s ON s.run_id = c.id
               GROUP BY c.id ORDER BY c.created_at DESC, c.rowid DESC"""
        ).fetchall()
    return [{**dict(r), "kabul": r["kabul"] or 0, "red": r["red"] or 0} for r in rows]


@app.get("/api/sets/{set_id}")
def get_set(set_id: str):
    with storage.db_session() as conn:
        s = _load_set(conn, set_id)
        if not s:
            raise HTTPException(404, "Kontrol seti bulunamadı.")
        s["controls"] = _controls(conn, set_id)
        s["messages"] = [
            {**dict(m), "changes": json.loads(m["changes"]) if m["changes"] else []}
            for m in conn.execute("SELECT * FROM set_messages WHERE set_id = ? ORDER BY id", (set_id,))
        ]
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


@app.post("/api/sets", status_code=202)
def create_set():
    """Yüklü belgelerden yeni kontrol seti üretimini arka planda başlatır.
    İlerleme: GET /api/sets/{id}/progress"""
    if jobs.is_running():
        raise HTTPException(409, "Şu an başka bir set üretiliyor. Bitmesini bekleyin ya da durdurun.")
    with storage.db_session() as conn:
        _backfill_documents(conn)
        rows = conn.execute("SELECT filename, stored_path, sha FROM documents ORDER BY id").fetchall()
    if not rows:
        raise HTTPException(400, "Önce en az bir belge yükleyin.")

    docs, skipped, seen = [], [], set()
    for d in rows:
        if d["sha"] and d["sha"] in seen:
            continue   # aynı içerik ikinci kez yüklenmiş: bir kez işlenir
        if d["sha"]:
            seen.add(d["sha"])
        p = Path(d["stored_path"])
        text = documents.extract_text(p) if p.exists() else ""
        if text.strip():
            docs.append((d["filename"], text))
        else:
            skipped.append(d["filename"])
    if not docs:
        raise HTTPException(400, "Yüklü belgelerin hiçbirinden metin okunamadı.")

    set_id = uuid.uuid4().hex[:10]
    names = [n for n, _ in docs]
    provisional = jobs.pretty_title(names[0]) if len(names) == 1 else f"{len(names)} belge"
    with storage.db_session() as conn:
        conn.execute(
            """INSERT INTO control_sets (id, baslik, belge_adlari, model, durum, hata)
               VALUES (?,?,?,?, 'uretiliyor', ?)""",
            (set_id, provisional, json.dumps(names, ensure_ascii=False), model_settings.active()["model"],
             f"Metni okunamayan belgeler atlandı: {', '.join(skipped)}" if skipped else None),
        )
    try:
        jobs.start(set_id, docs)
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
        s["controls"] = [dict(r) for r in rows]
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

    result = llm.chat_feedback(controls, focus, msg, skills.read_all_skills_text())
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
        cur = conn.execute(
            "INSERT INTO set_messages (set_id, control_id, role, content, changes, lesson) VALUES (?,?, 'ai', ?,?,?)",
            (set_id, body.control_id, result["yanit"], json.dumps(changes, ensure_ascii=False), result["ders"]),
        )
        ai_msg = dict(conn.execute("SELECT * FROM set_messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        ai_msg["changes"] = changes
        updated = _controls(conn, set_id)

    if result["ders"]:
        kategori = (focus or (by_id.get(changes[0]["id"]) if changes else None) or {}).get("kategori", "")
        skills.append_learning(skills.guess_skill_for_category(kategori), result["ders"])

    return {"ok": True, "message": ai_msg, "controls": updated}


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
    skill = skills.guess_skill_for_category(control["kategori"])
    if karar == "red":
        skills.append_learning(
            skill, f"Reddedildi: '{control['kontrol_adi']}' ({control['kategori']}, {control['siklik']}, risk {control['risk']}).")
    elif prev == "red":
        # ret geri alındı: o retten yazılan öğrenme de geri alınır
        skills.remove_last_learning_starting(skill, f"Reddedildi: '{control['kontrol_adi']}'")
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
        skills.append_learning(
            skills.guess_skill_for_category(control["kategori"]),
            f"Kullanıcı düzeltti — '{control['kontrol_adi']}': {'; '.join(diffs)}",
        )
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
        raise HTTPException(400, "Kütüphanede dışa aktarılacak kontrol yok.")
    from datetime import date
    meta = {"baslik": "Kontrol Kütüphanesi", "created_at": date.today().isoformat(),
            "ozet": f"Kabul edilmiş {len(items)} kontrol, {len({i['set_id'] for i in items})} kontrol setinden derlenmiştir.",
            "belge_adlari": sorted({i["kaynak_belge"] for i in items if i.get("kaynak_belge")})}
    return meta, items


@app.get("/api/library/export/word")
def library_word():
    meta, items = _library_export()
    return StreamingResponse(exporters.build_word(meta, items, library=True),
                             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": _disposition(f"Kontrol Kütüphanesi {meta['created_at']}.docx")})


@app.get("/api/library/export/excel")
def library_excel():
    meta, items = _library_export()
    return StreamingResponse(exporters.build_excel(meta, items, library=True),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": _disposition(f"Kontrol Kütüphanesi {meta['created_at']}.xlsx")})


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


@app.get("/api/skills")
def get_skills():
    return skills.list_skills()


class LearningEditIn(BaseModel):
    eski: str
    yeni: str | None = None


@app.patch("/api/skills/{name}/learnings")
def edit_learning(name: str, body: LearningEditIn):
    if not skills.skill_path(name):
        raise HTTPException(404, "Skill bulunamadı.")
    if not skills.edit_learning(name, body.eski, body.yeni or ""):
        raise HTTPException(400, "Kural bulunamadı ya da yeni metin boş.")
    return {"ok": True}


@app.post("/api/skills/{name}/learnings/archive")
def archive_learning(name: str, body: LearningEditIn):
    if not skills.skill_path(name):
        raise HTTPException(404, "Skill bulunamadı.")
    if not skills.archive_learning(name, body.eski):
        raise HTTPException(400, "Kural bulunamadı.")
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return {"kategoriler": llm.KATEGORILER, "sikliklar": llm.SIKLIKLAR,
            "riskler": llm.RISKLER, "eforlar": llm.EFORLAR}


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
