"""Word (.docx) ve Excel (.xlsx) dışa aktarımı — panel tasarımıyla aynı düzen."""
from datetime import datetime
from io import BytesIO

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

INK = RGBColor(0x1F, 0x20, 0x25)
MUTED = RGBColor(0x6E, 0x6F, 0x76)
KATEGORI_SIRASI = ["Operasyonel", "Mevzuat Uyum", "Bilgi Sistemleri", "Finansal Raporlama", "AML / Şüpheli İşlem"]
DURUM = {"bekliyor": "Bekliyor", "kabul": "Kabul", "red": "Red"}


def _durum(s):
    st = (s.get("status") or "bekliyor").lower()
    if st.startswith("düzenlendi"):
        return "Düzenlendi"
    return DURUM.get(st, st.capitalize())


def _grouped(controls):
    groups = {}
    for c in controls:
        groups.setdefault(c.get("kategori") or "Diğer", []).append(c)
    order = [k for k in KATEGORI_SIRASI if k in groups] + [k for k in groups if k not in KATEGORI_SIRASI]
    return [(k, groups[k]) for k in order]


def _shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def build_word(control_set: dict, controls: list[dict], library: bool = False) -> BytesIO:
    """library=True: Kontrol Kütüphanesi çıktısı (Durum yerine kontrolün geldiği set)."""
    doc = DocxDocument()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2)
    base = doc.styles["Normal"]
    base.font.name = "Calibri"
    base.font.size = Pt(10.5)
    base.font.color.rgb = INK

    h = doc.add_heading(control_set.get("baslik") or "Periyodik Kontroller", level=0)
    for r in h.runs:
        r.font.color.rgb = INK
        r.font.size = Pt(24)

    meta = doc.add_paragraph()
    belgeler = control_set.get("belge_adlari") or []
    parts = [
        f"{len(belgeler)} belge" if belgeler else None,
        (control_set.get("created_at") or "")[:10] or datetime.now().strftime("%Y-%m-%d"),
        f"{len(controls)} kontrol",
        control_set.get("model"),
    ]
    run = meta.add_run("  ·  ".join(p for p in parts if p))
    run.font.color.rgb = MUTED
    run.font.size = Pt(9.5)

    if control_set.get("ozet"):
        doc.add_paragraph(control_set["ozet"])

    for kategori, items in _grouped(controls):
        doc.add_heading(f"{kategori} ({len(items)})", level=2)
        table = doc.add_table(rows=1, cols=6)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"
        heads = ["Kontrol", "Sıklık", "Risk", "Efor", "Hat", "Set" if library else "Durum"]
        for i, t in enumerate(heads):
            cell = table.rows[0].cells[i]
            cell.text = ""
            r = cell.paragraphs[0].add_run(t)
            r.bold = True
            r.font.size = Pt(9)
            _shade(cell, "F3F2EF")
        for c in items:
            row = table.add_row().cells
            p = row[0].paragraphs[0]
            p.add_run(c.get("kontrol_adi") or "").bold = True
            if c.get("gerekce"):
                g = row[0].add_paragraph().add_run(c["gerekce"])
                g.font.size = Pt(9)
                g.font.color.rgb = MUTED
            if c.get("dayanak"):
                d = row[0].add_paragraph().add_run(f"Dayanak: {c['dayanak']}")
                d.font.size = Pt(8.5)
                d.font.color.rgb = MUTED
            if c.get("kaynak_belge"):
                src = f"Kaynak: {c['kaynak_belge']} · {c.get('kaynak_bolum') or ''}".rstrip(" ·")
                if c.get("kaynak_dogrulandi") == 0:
                    src += " (alıntı belgede bulunamadı)"
                k = row[0].add_paragraph().add_run(src)
                k.font.size = Pt(8.5)
                k.font.color.rgb = MUTED
            last = (c.get("set_baslik") or "—") if library else _durum(c)
            for i, val in enumerate([c.get("siklik"), c.get("risk"), c.get("efor"), c.get("hat"), last], start=1):
                row[i].text = str(val or "")
        for row in table.rows:
            row.cells[0].width = Cm(8.5)

    gaps = control_set.get("bosluklar") or []
    if gaps:
        doc.add_heading("Tespit edilen boşluklar", level=2)
        for g in gaps:
            doc.add_paragraph(g, style="List Bullet")

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(18)
    n = note.add_run("Periyodik Kontrol Asistanı tarafından üretilmiştir; kullanılmadan önce uzman gözden geçirmelidir.")
    n.italic = True
    n.font.size = Pt(8.5)
    n.font.color.rgb = MUTED

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


EXCEL_COLS = [
    ("Kontrol", "kontrol_adi", 48), ("Kategori", "kategori", 20), ("Hat", "hat", 6),
    ("Sıklık", "siklik", 16), ("Risk", "risk", 10), ("Efor", "efor", 10),
    ("Gerekçe", "gerekce", 60), ("Dayanak", "dayanak", 30),
    ("Kaynak belge", "kaynak_belge", 28), ("Kaynak bölüm", "kaynak_bolum", 28),
    ("Kaynak alıntı", "kaynak", 50), ("Alıntı doğrulandı", "_dogrulama", 14),
    ("Durum", None, 12),
]


def _dogrulama(c):
    v = c.get("kaynak_dogrulandi")
    return "—" if v is None else ("Evet" if v else "Hayır — belgede bulunamadı")


def build_excel(control_set: dict, controls: list[dict], library: bool = False) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Kontroller"
    thin = Side(style="thin", color="E6E5E0")
    head_fill = PatternFill("solid", fgColor="1F2025")

    cols = [(("Kaynak set", "set_baslik", 30) if key is None else (h, key, w)) for h, key, w in EXCEL_COLS] if library else EXCEL_COLS
    ws.append([c[0] for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22

    for kategori, items in _grouped(controls):
        for c in items:
            row = []
            for _, key, _ in cols:
                if key is None:
                    row.append(_durum(c))
                elif key == "_dogrulama":
                    row.append(_dogrulama(c))
                else:
                    row.append(c.get(key) or "")
            ws.append(row)

    for i, (_, _, width) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=thin)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    info = wb.create_sheet("Bilgi" if library else "Set bilgisi")
    rows = [
        ("Başlık", control_set.get("baslik") or ""),
        ("Oluşturulma", control_set.get("created_at") or ""),
        ("Model", control_set.get("model") or ""),
        ("Belgeler", ", ".join(control_set.get("belge_adlari") or [])),
        ("Özet", control_set.get("ozet") or ""),
    ] + [("Boşluk", g) for g in (control_set.get("bosluklar") or [])]
    for r in rows:
        info.append(list(r))
    info.column_dimensions["A"].width = 14
    info.column_dimensions["B"].width = 100
    for row in info.iter_rows():
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
