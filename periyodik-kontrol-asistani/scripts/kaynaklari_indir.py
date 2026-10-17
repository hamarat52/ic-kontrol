"""Uygulamayla gelen açık kaynakları (mevzuat, global standartlar) indirip düz metne çevirir.

Çalıştır (internet gerekir; işyeri sunucusunda değil, hazırlık makinesinde):
    python scripts/kaynaklari_indir.py            # eksikleri indir
    python scripts/kaynaklari_indir.py --hepsi    # hepsini yeniden indir (güncelleme)

Çıktı: app/kaynaklar/metin/<id>.txt (+ orijinal dosya app/kaynaklar/orijinal/), indirme
bilgisi app/kaynaklar/indirme.json. dagitim=yerel olanlar .gitignore'dadır.
"""
import html
import json
import re
import sys
import urllib.request
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent / "app" / "kaynaklar"
MANIFEST = json.loads((ROOT / "kaynaklar.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (PeriyodikKontrolAsistani kaynak indirici)"}
YENI_SATIR = re.compile(r"^(MADDE\s+\d|GEÇİCİ MADDE|EK MADDE|\(\d+\)|[a-zçğıöşü]{1,2}\)\s|[A-ZÇĞİÖŞÜ]\)|\d+\.\s|•|-\s)")


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def mevzuat_text(raw: bytes) -> str:
    """mevzuat.gov.tr birleştirilmiş metin sayfası → madde yapısını koruyan düz metin."""
    t = raw.decode("utf-8", errors="ignore").replace("\r", " ")
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", t)
    t = re.sub(r"(?i)</td>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", l).strip(" |") for l in t.split("\n")]
    lines = [l for l in lines if l.strip()]
    out: list[str] = []
    for l in lines:
        # Sayfa düzeni yüzünden kırılmış satırları birleştir; yeni madde/fıkra/bent ise yeni satır.
        if out and not YENI_SATIR.match(l) and not re.search(r"[.:;]$", out[-1]) and len(out[-1]) < 2000:
            out[-1] += " " + l
        else:
            out.append(l)
    # "MADDE n" satırlarının önüne boş satır: bölümleyici madde başlıklarını görsün
    text = "\n".join(out)
    text = re.sub(r"\n(?=(?:GEÇİCİ |EK )?MADDE \d)", "\n\n", text)
    return text.strip() + "\n"


def pdf_text(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw))
    pages = [(p.extract_text() or "") for p in reader.pages]
    text = "\n".join(pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main():
    hepsi = "--hepsi" in sys.argv
    (ROOT / "metin").mkdir(exist_ok=True)
    (ROOT / "orijinal").mkdir(exist_ok=True)
    kayit_yolu = ROOT / "indirme.json"
    kayit = json.loads(kayit_yolu.read_text(encoding="utf-8")) if kayit_yolu.exists() else {}
    for k in MANIFEST["kaynaklar"]:
        hedef = ROOT / "metin" / f"{k['id']}.txt"
        if hedef.exists() and not hepsi:
            continue
        src = k["kaynak"]
        try:
            if src["tip"] == "mevzuat":
                url = (f"https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?"
                       f"MevzuatTur={src['tur']}&MevzuatNo={src['no']}&MevzuatTertip=5")
                raw = fetch(url)
                text = mevzuat_text(raw)
                orj = ROOT / "orijinal" / f"{k['id']}.html"
                sayfa = f"https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={src['no']}&MevzuatTur={src['tur']}&MevzuatTertip=5"
            else:
                url = sayfa = src["url"]
                raw = fetch(url)
                if not raw.lstrip().startswith(b"%PDF"):
                    # Yayın sayfasına yönlendirildi (ör. BIS yeni adres yapısı): sayfadaki PDF bağlantısını izle
                    links = re.findall(rb'href="([^"]+\.pdf)"', raw)
                    if not links:
                        raise ValueError("PDF yerine HTML geldi ve sayfada PDF bağlantısı yok")
                    url = links[0].decode()
                    if url.startswith("/"):
                        url = re.match(r"https?://[^/]+", src["url"]).group(0) + url
                    raw = fetch(url)
                text = pdf_text(raw)
                orj = ROOT / "orijinal" / f"{k['id']}.pdf"
        except Exception as e:  # noqa: BLE001
            print(f"HATA  {k['id']}: {e}")
            continue
        if len(text) < 2000:
            print(f"HATA  {k['id']}: metin çok kısa ({len(text)} karakter), atlandı")
            continue
        orj.write_bytes(raw)
        hedef.write_text(text, encoding="utf-8")
        kayit[k["id"]] = {"url": sayfa, "erisim_tarihi": date.today().isoformat(),
                          "karakter": len(text), "sha256": sha256(raw).hexdigest(), "orijinal": orj.name}
        print(f"OK    {k['id']}: {len(text):,} karakter")
    kayit_yolu.write_text(json.dumps(kayit, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
