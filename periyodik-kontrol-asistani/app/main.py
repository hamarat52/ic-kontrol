import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, documents, llm, skills, storage

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
def list_suggestions():
    with storage.db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM suggestions ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


class FeedbackIn(BaseModel):
    karar: str  # "kabul" | "red" | "duzenle"
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
