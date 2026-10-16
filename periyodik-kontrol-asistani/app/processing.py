"""Belgeleri modele sığacak bölümlere ayırma, alıntı doğrulama ve tekrar ayıklama.

Hiçbir metin sessizce atılmaz: her satır tam olarak bir bölüme düşer.
"""
import re
import unicodedata
from difflib import SequenceMatcher

TARGET_CHARS = 5000   # bir bölüm için hedef uzunluk
MAX_CHARS = 7000      # bunu aşan tek satır/paragraf cümlelere bölünür
MIN_TAIL = 0.35       # hedefin bu oranından kısa bölümler öncekine eklenir (gereksiz model çağrısı olmasın)

_TOP_HEADING = re.compile(r"^\s*(?:#{1,6}\s+.+|\d{1,2}[.)]\s+[^\d\s].{1,80}|(?:BÖLÜM|KISIM|MADDE)\b.{0,80})\s*$", re.I)
_CAPS_HEADING = re.compile(r"^[A-ZÇĞİÖŞÜ0-9][A-ZÇĞİÖŞÜ0-9\s\-–:/,.()&]{3,90}$")


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if s.startswith("#"):
        return True
    if _TOP_HEADING.match(s) and not s.endswith((".", ";", ",")):
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and _CAPS_HEADING.match(s) is not None and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _clean_heading(line: str) -> str:
    return re.sub(r"^#+\s*", "", line.strip())[:80]


def _heading_rank(line: str) -> int:
    """Etiket önceliği: numaralı/markdown başlık (2) > büyük harfli satır (1)."""
    s = line.strip()
    if s.startswith("#") or re.match(r"^\d{1,2}[.)]\s", s) or re.match(r"^(BÖLÜM|KISIM|MADDE)\b", s, re.I):
        return 2
    return 1


def _split_long(line: str) -> list[str]:
    if len(line) <= MAX_CHARS:
        return [line]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?;:])\s+", line):
        while len(sent) > MAX_CHARS:  # noktalama olmayan devasa blok
            parts.append(sent[:MAX_CHARS])
            sent = sent[MAX_CHARS:]
        if len(cur) + len(sent) + 1 > TARGET_CHARS and cur:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def split_document(text: str, filename: str) -> list[dict]:
    """Metni başlık sınırlarını gözeterek ~TARGET_CHARS'lık bölümlere ayırır."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        lines.extend(_split_long(raw))

    chunks, cur, cur_len = [], [], 0
    heading = None          # o an geçerli başlık (bölüm ortasından başlayan parça için)
    start_heading = None    # parçanın başladığı andaki geçerli başlık
    found: list[tuple[int, str]] = []  # parça içinde görülen başlıklar

    def flush():
        nonlocal cur, cur_len, start_heading, found
        body = "\n".join(cur).strip()
        if body:
            strong = [h for r, h in found if r == 2]
            first = next((l for l in cur if l.strip()), "")
            if _is_heading(first):
                # parça yeni bir bölümle başlıyor: ilk numaralı başlık, yoksa ilk başlık
                label = strong[0] if strong else found[0][1]
            else:
                # parça bir bölümün ortasından başlıyor: o bölümün başlığı
                label = start_heading or (strong[0] if strong else (found[0][1] if found else None))
            chunks.append({"belge": filename, "bolum": label, "text": body})
        cur, cur_len, start_heading, found = [], 0, None, []

    for line in lines:
        is_head = _is_heading(line)
        if is_head:
            if cur_len >= TARGET_CHARS * 0.5:
                flush()
        elif cur_len + len(line) > TARGET_CHARS and cur_len > 0:
            flush()
        if not cur and not is_head:
            start_heading = heading
        if is_head:
            heading = _clean_heading(line)
            found.append((_heading_rank(line), heading))
        cur.append(line)
        cur_len += len(line) + 1
    flush()

    # Çok kısa parçaları komşusuna ekle (özellikle belge sonundaki kuyruk).
    merged: list[dict] = []
    for c in chunks:
        if merged and len(c["text"]) < TARGET_CHARS * MIN_TAIL and len(merged[-1]["text"]) + len(c["text"]) <= MAX_CHARS:
            merged[-1]["text"] += "\n" + c["text"]
        else:
            merged.append(c)
    chunks = merged

    for i, c in enumerate(chunks):
        c["index"] = i
        c["toplam"] = len(chunks)
        if not c["bolum"]:
            c["bolum"] = f"Bölüm {i + 1}"
    return chunks


# ------------------------------------------------------------------ alıntı doğrulama

def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").replace("İ", "i").replace("I", "ı").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("ı", "i")
    t = re.sub(r"[^0-9a-z]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def verify_quote(quote: str, source: str) -> bool | None:
    """Alıntı kaynakta geçiyor mu? None: doğrulanacak alıntı yok (çok kısa/boş)."""
    q = norm(quote)
    if len(q) < 12:
        return None
    s = norm(source)
    if q in s:
        return True
    m = SequenceMatcher(None, s, q, autojunk=False).find_longest_match(0, len(s), 0, len(q))
    return m.size / len(q) >= 0.85


# ------------------------------------------------------------------ tekrar ayıklama

_STOP = {
    "kontrol", "kontrolu", "kontrolü", "kontrolleri", "edilmesi", "yapilmasi", "yapılması", "ve", "ile", "icin",
    "için", "bir", "olan", "etme", "dogrulugunu", "doğruluğunu", "dogrulugu", "takibi", "izlenmesi", "tespiti",
    "gozden", "gecirilmesi", "periyodik", "duzenli", "uygunlugunun", "uygunluğu",
}


def _stem(w: str) -> str:
    """Kaba Türkçe kök: ekleri atmak için ilk 5 harf (hesaplarla→hesap, işlemleri→islem)."""
    return w[:5]


def _tokens(title: str) -> set[str]:
    stop = {norm(w) for w in _STOP}
    return {_stem(w) for w in norm(title).split() if len(w) > 2 and w not in stop}


def similarity(a_title: str, b_title: str) -> float:
    """0..1 benzerlik. Biri diğerini kapsıyor ve en fazla bir kelime fazlası varsa 1 sayılır."""
    a, b = _tokens(a_title), _tokens(b_title)
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    if len(small) >= 2 and small <= big and len(big) - len(small) <= 1:
        return 1.0
    return len(a & b) / len(a | b)


def find_similar(title: str, existing: list[str], threshold: float = 0.66) -> int | None:
    """En benzer kaydın indeksini döner (eşik üstündeyse)."""
    best, best_i = 0.0, None
    for i, other in enumerate(existing):
        s = similarity(title, other)
        if s > best:
            best, best_i = s, i
    return best_i if best >= threshold else None


def is_duplicate(title: str, existing: list[str], threshold: float = 0.66) -> bool:
    return find_similar(title, existing, threshold) is not None


def relevance(text: str, title: str) -> float:
    """Bir kontrol başlığının bir metinle ilgisi (başlık kelimelerinin metinde geçme oranı)."""
    t = _tokens(title)
    if not t:
        return 0.0
    words = {_stem(w) for w in norm(text).split()}
    return len(t & words) / len(t)
