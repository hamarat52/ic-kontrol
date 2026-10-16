import json
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, documents, exporters, llm, skills, storage

app = FastAPI(title="Periyodik Kontrol Asistanı")
storage.init_db()

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
    llm_ok = False
    try:
        r = httpx.get(f"{config.LLM_BASE_URL.rstrip('/')}/models", timeout=2,
                      headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        llm_ok = r.status_code < 400
    except Exception:
        pass
    return {"ok": True, "llm_ok": llm_ok, "llm_base_url": config.LLM_BASE_URL, "llm_model": config.LLM_MODEL}


# ------------------------------------------------------------------ belgeler

@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    name = file.filename or "belge"
    suffix = Path(name).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Yalnız pdf, docx, txt ve md dosyaları kabul edilir.")
    dest = config.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(await file.read())
    text = documents.extract_text(dest)
    with storage.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, stored_path, text_excerpt, char_count) VALUES (?,?,?,?)",
            (name, str(dest), text[:2000], len(text)),
        )
        doc = _row(conn.execute("SELECT id, filename, char_count, uploaded_at FROM documents WHERE id=?",
                                (cur.lastrowid,)).fetchone())
    return doc


@app.get("/api/documents")
def list_documents():
    with storage.db_session() as conn:
        rows = conn.execute(
            "SELECT id, filename, char_count, uploaded_at FROM documents ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


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
    with storage.db_session() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM suggestions WHERE run_id = ?", (set_id,))]
        if ids:
            q = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM feedback WHERE suggestion_id IN ({q})", ids)
        conn.execute("DELETE FROM suggestions WHERE run_id = ?", (set_id,))
        conn.execute("DELETE FROM set_messages WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM control_sets WHERE id = ?", (set_id,))
    return {"ok": True}


@app.post("/api/sets")
def create_set():
    """Yüklü belgelerden yeni kontrol seti üretir. Yanıt NDJSON akışıdır:
    set → meta → control* → gap* → done | error."""
    with storage.db_session() as conn:
        docs = conn.execute("SELECT filename, stored_path FROM documents ORDER BY id").fetchall()
    if not docs:
        raise HTTPException(400, "Önce en az bir belge yükleyin.")

    combined, names = "", []
    for d in docs:
        p = Path(d["stored_path"])
        if p.exists():
            names.append(d["filename"])
            combined += f"\n\n--- Belge: {d['filename']} ---\n{documents.extract_text(p)}"

    set_id = uuid.uuid4().hex[:10]
    with storage.db_session() as conn:
        conn.execute(
            "INSERT INTO control_sets (id, baslik, belge_adlari, model, durum) VALUES (?,?,?,?, 'uretiliyor')",
            (set_id, "", json.dumps(names, ensure_ascii=False), config.LLM_MODEL),
        )
    skills_text = skills.read_all_skills_text()

    def line(obj):
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def gen():
        gaps, count, finished = [], 0, False
        try:
            with storage.db_session() as conn:
                yield line({"event": "set", "set": _load_set(conn, set_id)})
            for ev in llm.stream_control_set(combined, skills_text):
                kind = ev["event"]
                if kind == "meta":
                    with storage.db_session() as conn:
                        conn.execute("UPDATE control_sets SET baslik = ?, ozet = ? WHERE id = ?",
                                     (ev["baslik"], ev["ozet"], set_id))
                    yield line(ev)
                elif kind == "control":
                    c = ev["control"]
                    with storage.db_session() as conn:
                        cur = conn.execute(
                            """INSERT INTO suggestions (run_id, kontrol_adi, kategori, hat, siklik, risk,
                                                         efor, gerekce, dayanak, kaynak)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (set_id, c["kontrol_adi"], c["kategori"], c["hat"], c["siklik"], c["risk"],
                             c["efor"], c["gerekce"], c["dayanak"], c["kaynak"]),
                        )
                        row = dict(conn.execute("SELECT * FROM suggestions WHERE id = ?",
                                                (cur.lastrowid,)).fetchone())
                    row["edited"] = 0
                    count += 1
                    yield line({"event": "control", "control": row})
                elif kind == "gap":
                    if ev["metin"]:
                        gaps.append(ev["metin"])
                        yield line(ev)
                elif kind == "error":
                    with storage.db_session() as conn:
                        conn.execute("UPDATE control_sets SET hata = ? WHERE id = ?", (ev["error"], set_id))
                    yield line(ev)
            with storage.db_session() as conn:
                conn.execute(
                    """UPDATE control_sets SET durum = ?, bosluklar = ?,
                         baslik = CASE WHEN baslik IS NULL OR baslik = '' THEN ? ELSE baslik END
                       WHERE id = ?""",
                    ("hazir" if count else "hata", json.dumps(gaps, ensure_ascii=False),
                     (Path(names[0]).stem if names else "Kontrol seti"), set_id),
                )
                final = _load_set(conn, set_id)
            finished = True
            yield line({"event": "done", "set": final, "count": count})
        finally:
            if not finished:  # istemci bağlantıyı kesti
                with storage.db_session() as conn:
                    conn.execute(
                        "UPDATE control_sets SET durum = ?, bosluklar = ?, hata = COALESCE(hata, 'Üretim yarıda kesildi') WHERE id = ?",
                        ("hazir" if count else "hata", json.dumps(gaps, ensure_ascii=False), set_id),
                    )

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@app.post("/api/controls/{control_id}/decision")
def decide(control_id: int, body: DecisionIn):
    if body.karar not in ("kabul", "red", "bekliyor"):
        raise HTTPException(400, "Geçersiz karar.")
    with storage.db_session() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (control_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Kontrol bulunamadı.")
        control = dict(row)
        if control["status"] == body.karar:
            return {"ok": True, "control": control}
        conn.execute("UPDATE suggestions SET status = ? WHERE id = ?", (body.karar, control_id))
        conn.execute("INSERT INTO feedback (suggestion_id, karar) VALUES (?, ?)", (control_id, body.karar))
        control["status"] = body.karar
        _sync_library(conn, control)
    if body.karar == "red":
        skills.append_learning(
            skills.guess_skill_for_category(control["kategori"]),
            f"Reddedildi: '{control['kontrol_adi']}' ({control['kategori']}, {control['siklik']}, risk {control['risk']}).",
        )
    return {"ok": True, "control": control}


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
            """SELECT l.*, c.baslik AS set_baslik FROM library l
               LEFT JOIN control_sets c ON c.id = l.set_id ORDER BY l.kategori, l.kontrol_adi"""
        ).fetchall()
    return [dict(r) for r in rows]


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
