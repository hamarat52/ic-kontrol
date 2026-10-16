"""Word (.docx) ve Excel (.xlsx) dışa aktarım üretimi."""
from datetime import datetime
from io import BytesIO

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = ["Kontrol Adı", "Kategori", "Hat", "Sıklık", "Risk", "Efor", "Gerekçe", "Durum"]
FIELD_KEYS = ["kontrol_adi", "kategori", "hat", "siklik", "risk", "efor", "gerekce", "status"]

ACCENT_HEX = "4F46E5"


def build_word(suggestions: list[dict], run_id: str) -> BytesIO:
    doc = DocxDocument()
    title = doc.add_heading("Periyodik Kontrol Önerileri", level=1)
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x4F, 0x46, 0xE5)

    meta = doc.add_paragraph()
    meta.add_run(f"Çalışma No: {run_id}  ·  Oluşturulma: ").italic = True
    meta.add_run(datetime.now().strftime("%Y-%m-%d %H:%M")).italic = True

    table = doc.add_table(rows=1, cols=len(HEADERS))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Light Grid Accent 1"
    hdr_cells = table.rows[0].cells
    for i, header in enumerate(HEADERS):
        hdr_cells[i].text = header
        for p in hdr_cells[i].paragraphs:
            for r in p.runs:
                r.font.bold = True

    for s in suggestions:
        cells = table.add_row().cells
        for i, key in enumerate(FIELD_KEYS):
            cells[i].text = str(s.get(key) or "")

    doc.add_paragraph()
    note = doc.add_paragraph()
    note.add_run(
        "Bu belge Periyodik Kontrol Asistanı tarafından otomatik üretilmiştir; "
        "yayımlanmadan önce ilgili uzman tarafından gözden geçirilmelidir."
    ).italic = True

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def build_excel(suggestions: list[dict], run_id: str) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Periyodik Kontroller"

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=ACCENT_HEX)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for s in suggestions:
        ws.append([s.get(key) or "" for key in FIELD_KEYS])

    for col_cells in ws.columns:
        length = max((len(str(c.value)) for c in col_cells if c.value), default=10)
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(
            max(length + 2, 12), 50
        )
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
