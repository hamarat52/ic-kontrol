"""Yüklenen dokümanlardan metin çıkarma (PDF / DOCX / TXT)."""
from pathlib import Path

from pypdf import PdfReader
from docx import Document as DocxDocument


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix == ".docx":
            doc = DocxDocument(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        if suffix in (".txt", ".md"):
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # metin çıkarılamazsa uygulama çökmesin
        return f"[Metin çıkarılamadı: {exc}]"
    return "[Desteklenmeyen dosya türü: yalnız pdf, docx, txt, md kabul edilir]"
