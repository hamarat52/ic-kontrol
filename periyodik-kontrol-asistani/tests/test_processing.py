from pathlib import Path

from app import processing as P

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "ornek-veri" / "sentetik-kredi-tahsis-proseduru.txt").read_text(encoding="utf-8")


def _lines(text):
    return [l for l in text.splitlines() if l.strip()]


def test_no_text_is_lost_and_order_kept():
    big = SAMPLE * 6
    chunks = P.split_document(big, "x.txt")
    assert len(chunks) > 1
    joined = [l for c in chunks for l in _lines(c["text"])]
    assert joined == _lines(big)
    assert all(len(c["text"]) <= P.MAX_CHARS + 200 for c in chunks)
    assert [c["index"] for c in chunks] == list(range(len(chunks)))
    assert all(c["toplam"] == len(chunks) for c in chunks)


def test_headings_used_as_section_labels():
    chunks = P.split_document(SAMPLE * 6, "x.txt")
    labels = {c["bolum"] for c in chunks}
    assert any(l.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.")) or "PROSEDÜR" in l for l in labels)
    assert P._is_heading("4. Risk Analizi")
    assert P._is_heading("## Tahsis Yetkileri")
    assert P._is_heading("KREDİ TAHSİS PROSEDÜRÜ")
    assert not P._is_heading("4.1. Her kredi başvurusu, tahsis onayından önce Risk Analizi Biriminin değerlendirmesinden geçer.")


def test_small_doc_is_single_chunk_with_fallback_label():
    chunks = P.split_document("tek satır metin", "a.txt")
    assert len(chunks) == 1 and chunks[0]["bolum"] == "Bölüm 1"


def test_short_tail_is_merged_and_labels_prefer_numbered_headings():
    chunks = P.split_document(SAMPLE, "kredi.txt")      # ~2.000 karakter: tek bölüm olmalı
    assert len(chunks) == 1
    assert chunks[0]["bolum"] == "1. Amaç ve Kapsam"     # kapak satırı değil, ilk numaralı başlık


def test_chunk_starting_mid_section_keeps_section_label():
    body = "3. Risk Analizi\n" + "\n".join(f"3.{i}. " + "çok uzun bir kural cümlesi " * 12 for i in range(1, 60))
    chunks = P.split_document(body, "x.txt")
    assert len(chunks) > 1
    assert all(c["bolum"] == "3. Risk Analizi" for c in chunks)


def test_giant_line_without_newlines_is_split():
    text = ("Bu çok uzun bir cümledir ve tekrar eder. " * 600)
    chunks = P.split_document(text, "pdf.txt")
    assert len(chunks) >= 4
    assert P.norm(" ".join(c["text"] for c in chunks)) == P.norm(text)


def test_verify_quote():
    src = "4.1. Her kredi başvurusu, tahsis onayından önce Risk Analizi Biriminin değerlendirmesinden geçer."
    assert P.verify_quote("tahsis onayından önce RİSK ANALİZİ biriminin değerlendirmesinden geçer", src) is True
    assert P.verify_quote("tahsis onayindan once risk analizi biriminin degerlendirmesinden gecer", src) is True
    assert P.verify_quote("Kredi komitesi her hafta toplanarak tüm başvuruları karara bağlar", src) is False
    assert P.verify_quote("kısa", src) is None
    assert P.verify_quote("", src) is None


def test_duplicates():
    existing = ["Risk analizi yapılmadan onaylanan başvuruların tespiti"]
    assert P.is_duplicate("Risk Analizi Yapılmadan Onaylanan Başvuruların Kontrolü", existing)
    assert not P.is_duplicate("Teminat değerleme raporlarının güncelliği", existing)
