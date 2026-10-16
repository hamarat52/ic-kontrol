import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, documents, exporters, llm, skills, storage

app = FastAPI(title="Periyodik Kontrol Asistanı")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

storage.init_db()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "llm_base_url": config.LLM_BASE_URL,
        "llm_model": config.LLM_MODEL,
    }


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Yalnız pdf, docx, txt, md dosyaları kabul edilir.")

    dest_name = f"{uuid.uuid4().hex}{suffix}"
    dest_path = config.UPLOADS_DIR / dest_name
    content = await file.read()
    dest_path.write_bytes(content)

    text = documents.extract_text(dest_path)

    with storage.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, stored_path, text_excerpt) VALUES (?, ?, ?)",
            (file.filename, str(dest_path), text[:2000]),
        )
        doc_id = cur.lastrowid

    return {"id": doc_id, "filename": file.filename, "char_count": len(text)}


@app.get("/api/documents")
def list_documents():
    with storage.db_session() as conn:
        rows = conn.execute(
            "SELECT id, filename, uploaded_at FROM documents ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    with storage.db_session() as conn:
        row = conn.execute(
            "SELECT stored_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Doküman bulunamadı.")
        Path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return {"ok": True}


@app.get("/api/skills")
def get_skills():
    return skills.list_skills()


@app.post("/api/periyodik-kontrolleri-cikart")
def generate():
    with storage.db_session() as conn:
        rows = conn.execute("SELECT stored_path, filename FROM documents").fetchall()

    if not rows:
        raise HTTPException(400, "Önce en az bir belge yükleyin.")

    combined_text = ""
    for row in rows:
        path = Path(row["stored_path"])
        if path.exists():
            combined_text += f"\n\n--- Belge: {row['filename']} ---\n"
            combined_text += documents.extract_text(path)

    skills_text = skills.read_all_skills_text()
    result = llm.generate_suggestions(combined_text, skills_text)

    if not result["ok"]:
        return {"ok": False, "error": result["error"]}

    run_id = uuid.uuid4().hex[:8]
    saved = []
    with storage.db_session() as conn:
        for s in result["suggestions"]:
            cur = conn.execute(
                """INSERT INTO suggestions
                   (run_id, kontrol_adi, kategori, hat, siklik, risk, efor, gerekce)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    s.get("kontrol_adi"),
                    s.get("kategori"),
                    s.get("hat"),
                    s.get("siklik"),
                    s.get("risk"),
                    s.get("efor"),
                    s.get("gerekce"),
                ),
            )
            s["id"] = cur.lastrowid
            saved.append(s)

    return {"ok": True, "run_id": run_id, "suggestions": saved}


@app.get("/api/suggestions")
def list_suggestions(run_id: str | None = None):
    with storage.db_session() as conn:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM suggestions WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM suggestions ORDER BY id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


class FeedbackIn(BaseModel):
    karar: str  # "kabul" | "red"
    not_metni: str | None = None


@app.post("/api/suggestions/{suggestion_id}/feedback")
def submit_feedback(suggestion_id: int, body: FeedbackIn):
    with storage.db_session() as conn:
        row = conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Öneri bulunamadı.")

        conn.execute(
            "INSERT INTO feedback (suggestion_id, karar, not_metni) VALUES (?, ?, ?)",
            (suggestion_id, body.karar, body.not_metni),
        )
        conn.execute(
            "UPDATE suggestions SET status = ? WHERE id = ?",
            (body.karar, suggestion_id),
        )

    # Skill dosyasını güncelle: kullanıcı geri bildirimini "Öğrenilenler"e ekle.
    skill_name = skills.guess_skill_for_category(row["kategori"])
    learning = (
        f"Öneri '{row['kontrol_adi']}' (kategori: {row['kategori']}, risk: {row['risk']}) "
        f"için karar: {body.karar}."
    )
    if body.not_metni:
        learning += f" Not: {body.not_metni}"
    skills.append_learning(skill_name, learning)

    return {"ok": True, "updated_skill": skill_name}


EDITABLE_FIELDS = ("kontrol_adi", "kategori", "hat", "siklik", "risk", "efor", "gerekce")


class EditIn(BaseModel):
    kontrol_adi: str | None = None
    kategori: str | None = None
    hat: str | None = None
    siklik: str | None = None
    risk: str | None = None
    efor: str | None = None
    gerekce: str | None = None


@app.patch("/api/suggestions/{suggestion_id}")
def edit_suggestion(suggestion_id: int, body: EditIn):
    """Kullanıcının bir önerinin içeriğini doğrudan değiştirmesi (serbest metin değil)."""
    with storage.db_session() as conn:
        row = conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Öneri bulunamadı.")

        updates = {
            k: v for k, v in body.model_dump().items() if v is not None and v != row[k]
        }
        if not updates:
            return {"ok": True, "changed": False}

        diffs = [f"{k}: '{row[k]}' -> '{v}'" for k, v in updates.items()]
        set_clause = ", ".join(f"{k} = ?" for k in updates) + ", status = 'düzenlendi'"
        conn.execute(
            f"UPDATE suggestions SET {set_clause} WHERE id = ?",
            (*updates.values(), suggestion_id),
        )
        conn.execute(
            "INSERT INTO feedback (suggestion_id, karar, not_metni) VALUES (?, 'duzenle', ?)",
            (suggestion_id, "; ".join(diffs)),
        )
        updated_row = conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()

    skill_name = skills.guess_skill_for_category(updates.get("kategori", row["kategori"]))
    skills.append_learning(
        skill_name, f"Öneri '{row['kontrol_adi']}' manuel düzenlendi: {'; '.join(diffs)}"
    )
    return {"ok": True, "changed": True, "suggestion": dict(updated_row)}


class PromptFeedbackIn(BaseModel):
    prompt: str


@app.post("/api/suggestions/{suggestion_id}/prompt-feedback")
def prompt_feedback(suggestion_id: int, body: PromptFeedbackIn):
    """Kullanıcının bir öneriye serbest metinle ('bu kontrol çok sık olmuş' vb.) verdiği
    geri bildirimi LLM ile değerlendirir: gerekirse alanları günceller, her durumda
    genelleştirilmiş bir dersi ilgili skill dosyasına ekler."""
    with storage.db_session() as conn:
        row = conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Öneri bulunamadı.")
    suggestion_dict = dict(row)

    skills_text = skills.read_all_skills_text()
    result = llm.process_prompt_feedback(suggestion_dict, skills_text, body.prompt)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}

    applied_fields = None
    raw_updates = result.get("alan_guncellemesi") or {}
    updates = {k: v for k, v in raw_updates.items() if k in EDITABLE_FIELDS and v}

    with storage.db_session() as conn:
        conn.execute(
            "INSERT INTO feedback (suggestion_id, karar, not_metni) VALUES (?, 'prompt', ?)",
            (suggestion_id, body.prompt),
        )
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates) + ", status = 'düzenlendi (prompt)'"
            conn.execute(
                f"UPDATE suggestions SET {set_clause} WHERE id = ?",
                (*updates.values(), suggestion_id),
            )
            applied_fields = updates
        updated_row = conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()

    skill_name = skills.guess_skill_for_category(suggestion_dict["kategori"])
    lesson = result.get("ders") or (
        f"Kullanıcı '{suggestion_dict['kontrol_adi']}' önerisine şu geri bildirimi verdi: "
        f"{body.prompt}"
    )
    skills.append_learning(skill_name, lesson)

    return {
        "ok": True,
        "applied_fields": applied_fields,
        "lesson": lesson,
        "suggestion": dict(updated_row),
    }


def _suggestions_for_export(run_id: str | None) -> list[dict]:
    with storage.db_session() as conn:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM suggestions WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM suggestions ORDER BY id ASC").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/export/word")
def export_word(run_id: str | None = None):
    suggestions = _suggestions_for_export(run_id)
    if not suggestions:
        raise HTTPException(400, "Dışa aktarılacak öneri yok.")
    buf = exporters.build_word(suggestions, run_id or "tumu")
    filename = f"periyodik-kontroller-{run_id or 'tumu'}.docx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/excel")
def export_excel(run_id: str | None = None):
    suggestions = _suggestions_for_export(run_id)
    if not suggestions:
        raise HTTPException(400, "Dışa aktarılacak öneri yok.")
    buf = exporters.build_excel(suggestions, run_id or "tumu")
    filename = f"periyodik-kontroller-{run_id or 'tumu'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
