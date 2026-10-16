"""Yüklenen belgelerden metin çıkarma (PDF / DOCX / TXT / MD).

Hata veya boş metin durumunda metin yerine açık bir uyarı döner; uyarı metni
asla model girdisine karışmaz.
"""
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


def _docx_text(path: Path) -> str:
    doc = DocxDocument(str(path))
    out = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith(("heading", "başlık", "title", "konu başlığı")):
                out.append(f"# {text}")
            else:
                out.append(text)
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells, seen = [], set()
                for cell in row.cells:  # birleştirilmiş hücreler tekrar eder
                    t = cell.text.strip().replace("\n", " ")
                    if t and id(cell._tc) not in seen:
                        cells.append(t)
                        seen.add(id(cell._tc))
                if cells:
                    out.append(" | ".join(cells))
    return "\n".join(out)


def _plain_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1254", "latin-1"):  # Windows Türkçe dosyalar cp1254 olabilir
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract(path: Path) -> tuple[str, str | None]:
    """Döner: (metin, uyarı). Uyarı varsa metin boş olabilir."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if len(text.strip()) < 50:
                return text, "PDF'ten metin okunamadı — taranmış (görüntü) bir belge olabilir. Metin içeren PDF ya da Word yükleyin."
            return text, None
        if suffix == ".docx":
            text = _docx_text(path)
        elif suffix in (".txt", ".md"):
            text = _plain_text(path)
        else:
            return "", "Desteklenmeyen dosya türü (yalnız pdf, docx, txt, md)."
    except Exception as exc:
        return "", f"Metin çıkarılamadı: {exc}"
    if not text.strip():
        return text, "Belgede metin bulunamadı."
    return text, None


def extract_text(path: Path) -> str:
    """Geriye dönük uyum: yalnız metni döner (uyarıda boş metin)."""
    text, warning = extract(path)
    return "" if warning and not text.strip() else text
