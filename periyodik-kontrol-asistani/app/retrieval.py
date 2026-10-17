"""Dayanak araması: açık kaynakları (mevzuat, standartlar) ve şirket organizasyon belgelerini
madde/paragraf parçalarına bölüp, bir uygulama esası bölümüyle en ilgili parçaları bulur.

İnternetsiz ve model gerektirmez: Türkçe eklere dayanıklı kök + BM25 puanlaması.
Bulunan parçalar prompt'a "dayanak adayı" olarak eklenir; modelden kontrol üretmesi
istenmez, yalnız "Dayanak" alanında doğru madde göstermesi istenir.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from . import processing

PIECE_CHARS = 1400        # bir parçanın hedef uzunluğu
PIECE_MAX = 2200

_MADDE = re.compile(r"(?:(?<=\n)|(?<=\s))((?:GEÇİCİ|Geçici|EK|Ek)\s+)?(MADDE|Madde)\s+(\d+[A-Za-z/]*)\s*[–—-]")
_PRINCIPLE = re.compile(r"(?m)^\s*(Principle\s+\d+|\d{1,2}\.\s+[A-Z][^\n]{3,80}|[A-Z]{2}\.[A-Z]{2}(?:-\d{2})?:?)")

_STOP = {processing.norm(w) for w in (
    "ve veya ile için bu bir her olarak olan da de ki ise gibi daha en çok tüm kadar sonra önce göre "
    "ilgili ilişkin hakkında madde fıkra bent yönetmelik kanun banka bankalar bankanın kurum kurul "
    "the of and to a in for or be by on with as is are that this which should must may an at from its"
).split()}


def _terms(text: str) -> list[str]:
    return [processing._stem(w) for w in processing.norm(text).split()
            if len(w) > 2 and w not in _STOP and not w.isdigit()]


def _split_long(label: str, body: str) -> list[dict]:
    if len(body) <= PIECE_MAX:
        return [{"label": label, "text": body}]
    out, cur = [], ""
    for para in re.split(r"\n+", body):
        if cur and len(cur) + len(para) > PIECE_CHARS:
            out.append(cur)
            cur = ""
        cur = (cur + "\n" + para).strip()
    if cur:
        out.append(cur)
    return [{"label": label if i == 0 else f"{label} (devam)", "text": t} for i, t in enumerate(out)]


def split_pieces(text: str) -> list[dict]:
    """Mevzuat: madde madde; diğerleri: başlıklı paragraf grupları."""
    marks = list(_MADDE.finditer(text))
    pieces: list[dict] = []
    if len(marks) >= 3:
        # Madde başlığı (ör. "Amaç", "Dayanak") maddeden hemen önceki kısa satırdır; önceki
        # maddenin metnine karışmasın diye her maddenin sonu, sonrakinin başlık satırında biter.
        titles, starts = [], []
        def _title_ok(s):
            return 0 < len(s) <= 60 and not s.endswith((".", ";", ":", ",")) and not re.search(r"\d{4}", s)
        for m in marks:
            ls = text.rfind("\n", 0, m.start()) + 1
            same = text[ls:m.start()].strip()
            if same:   # eski kanun biçimi: "Kapsam Madde 2 — …" başlık aynı satırda
                ok = _title_ok(same)
                titles.append(same if ok else "")
                starts.append(ls if ok else m.start())
                continue
            ps, prev = ls, ""
            for _ in range(3):                                 # önceki boş olmayan satır
                if ps <= 0:
                    break
                ps = text.rfind("\n", 0, ps - 1) + 1
                prev = text[ps:text.find("\n", ps) if text.find("\n", ps) >= 0 else len(text)].strip()
                if prev:
                    break
            ok = ls > 0 and _title_ok(prev)
            titles.append(prev if ok else "")
            starts.append(ps if ok else m.start())
        for i, m in enumerate(marks):
            end = starts[i + 1] if i + 1 < len(marks) else len(text)
            title = titles[i]
            kind = {"GEÇİCİ": "Geçici", "EK": "Ek"}.get((m.group(1) or "").strip(), (m.group(1) or "").strip())
            label = f"{kind + ' ' if kind else ''}Madde {m.group(3)}{' — ' + title if title else ''}"
            pieces += _split_long(label, text[m.start():end].strip())
        return pieces
    # Madde yapısı yok (standartlar, şirket belgeleri): başlıkları etiket yap
    heading, cur = "Giriş", ""
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        is_head = (processing._is_heading(s) or _PRINCIPLE.match(s)) and len(s) <= 90
        if is_head and len(cur) >= PIECE_CHARS * 0.5:
            pieces.append({"label": heading, "text": cur.strip()})
            cur = ""
        if is_head:
            heading = re.sub(r"^#+\s*", "", s)[:70]
        if len(cur) + len(s) > PIECE_MAX and cur:
            pieces.append({"label": heading, "text": cur.strip()})
            cur = ""
        cur += s + "\n"
    if cur.strip():
        pieces.append({"label": heading, "text": cur.strip()})
    return pieces


class Index:
    """Birden çok belge üzerinde BM25 dizini."""

    def __init__(self, docs: list[dict]):
        # docs: [{"id", "ad", "text"}]
        self.pieces: list[dict] = []
        for d in docs:
            for p in split_pieces(d["text"]):
                terms = _terms(p["label"] + " " + p["text"])
                if terms:
                    self.pieces.append({**p, "doc_id": d["id"], "doc": d["ad"], "tf": Counter(terms), "len": len(terms)})
        n = len(self.pieces) or 1
        df = Counter(t for p in self.pieces for t in p["tf"])
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.avg = sum(p["len"] for p in self.pieces) / n

    def search(self, query: str, k: int = 4, budget: int = 4500, k1: float = 1.4, b: float = 0.75) -> list[dict]:
        q = Counter(_terms(query))
        # Sorgunun en ayırt edici 40 terimi (uzun bölümlerde gürültüyü azaltır)
        q_terms = sorted(q, key=lambda t: -self.idf.get(t, 0) * min(q[t], 3))[:40]
        scored = []
        for p in self.pieces:
            s = 0.0
            for t in q_terms:
                f = p["tf"].get(t)
                if f:
                    s += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * p["len"] / self.avg))
            if s > 0:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        out, used, per_doc = [], 0, Counter()
        for s, p in scored:
            if len(out) >= k or used + len(p["text"]) > budget:
                continue
            if per_doc[p["doc_id"]] >= 2:          # tek belge tüm bütçeyi yemesin
                continue
            out.append({"doc_id": p["doc_id"], "doc": p["doc"], "label": p["label"], "text": p["text"], "score": round(s, 2)})
            used += len(p["text"])
            per_doc[p["doc_id"]] += 1
        return out


def format_block(hits: list[dict], title: str) -> str:
    if not hits:
        return ""
    parts = [f"[{i + 1}] {h['doc']} — {h['label']}\n{h['text']}" for i, h in enumerate(hits)]
    return f"{title}\n" + "\n\n".join(parts)


def load_texts(rows: list[dict]) -> list[dict]:
    """documents satırlarından (id, filename/ad, stored_path) metinleri okur."""
    from . import documents
    out = []
    for r in rows:
        p = Path(r["stored_path"])
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8") if p.suffix == ".txt" else documents.extract(p)[0]
        if text.strip():
            out.append({"id": r["id"], "ad": r.get("ad") or r["filename"], "text": text})
    return out
