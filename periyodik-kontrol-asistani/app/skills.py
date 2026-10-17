"""Skill dosyalarını okuma ve geri bildirimle güncelleme.

Hermes skill mantığına benzer: her skill bir markdown dosyası, "Öğrenilenler"
bölümü kullanım/geri bildirim arttıkça büyür. Şimdilik güncelleme kural
tabanlı (LLM olmadan da çalışır); LLM varsa daha nitelikli özetleme için
kullanılabilir (bkz. llm.summarize_feedback_for_skill).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from . import config

SEED_DIR = Path(__file__).resolve().parent / "seed_skills"


def ensure_seed() -> None:
    """Başlangıç skill'lerini (app/seed_skills, sürüm kontrollü) çalışma klasörüne
    (data/skills, kullanıcıya özel, git dışı) yalnız eksikse kopyalar.
    Kullanıcının öğrendikleri asla üzerine yazılmaz."""
    config.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for seed in SEED_DIR.glob("*.md"):
        target = config.SKILLS_DIR / seed.name
        if not target.exists():
            target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")


def list_skills() -> list[dict]:
    ensure_seed()
    skills = []
    for path in sorted(config.SKILLS_DIR.glob("*.md")):
        skills.append({"name": path.stem, "content": path.read_text(encoding="utf-8")})
    return skills


def read_all_skills_text() -> str:
    """Prompt'a eklemek için tüm skill içeriğini birleştirir."""
    parts = []
    for skill in list_skills():
        parts.append(f"## Skill: {skill['name']}\n{skill['content']}")
    return "\n\n".join(parts)


def append_learning(skill_name: str, learning_text: str) -> None:
    """Bir skill dosyasının 'Öğrenilenler' bölümüne yeni bir madde ekler."""
    path = config.SKILLS_DIR / f"{skill_name}.md"
    if not path.exists():
        path.write_text(f"# Skill: {skill_name}\n\n## Öğrenilenler\n", encoding="utf-8")

    content = path.read_text(encoding="utf-8")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- [{timestamp}] {learning_text}\n"

    marker = "## Öğrenilenler"
    if marker in content:
        if "_(henüz geri bildirim yok" in content:
            # placeholder satırını ilk gerçek girdiyle değiştir
            idx = content.index(marker)
            before, after = content[: idx + len(marker)], content[idx + len(marker):]
            after_lines = after.split("\n")
            cleaned = [
                line for line in after_lines if "_(henüz geri bildirim yok" not in line
            ]
            content = before + "\n".join(cleaned)
        content = content.rstrip("\n") + "\n" + entry
    else:
        content = content.rstrip("\n") + f"\n\n{marker}\n{entry}"

    path.write_text(content, encoding="utf-8")


def guess_skill_for_category(kategori: str) -> str:
    kategori_l = (kategori or "").lower()
    if "masak" in kategori_l or "aml" in kategori_l or "şüpheli" in kategori_l:
        return "masak-aml"
    return "kontrol-metrikleri"


# ---------------------------------------------------------------- öğrenilenleri yönetme

_ENTRY = re.compile(r"^- \[(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\]\s*(.+)$")


def skill_path(name: str) -> Path | None:
    """Yalnız var olan skill dosyalarına izin verir (yol enjeksiyonu yok)."""
    if not re.fullmatch(r"[a-z0-9-]{1,60}", name or ""):
        return None
    p = config.SKILLS_DIR / f"{name}.md"
    return p if p.exists() else None


def _archive(name: str, line: str, reason: str) -> None:
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "skill": name, "satir": line, "neden": reason}
    with open(config.DATA_DIR / "skills_arsiv.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _rewrite(name: str, fn) -> bool:
    """Öğrenilenler bölümündeki her madde satırına fn(ts, text) uygular.
    fn: None (dokunma) | "" (sil) | yeni metin döndürür. Bir satır değiştiyse True."""
    path = skill_path(name)
    if not path:
        return False
    lines = path.read_text(encoding="utf-8").split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Öğrenilenler")
    except StopIteration:
        return False
    changed = False
    out = lines[: start + 1]
    for line in lines[start + 1:]:
        m = _ENTRY.match(line)
        res = fn(m.group(1), m.group(2)) if m else None
        if res is None:
            out.append(line)
            continue
        changed = True
        if res == "":
            _archive(name, line, "arşivlendi")
        else:
            out.append(f"- [{m.group(1)}] {res}")
    if changed:
        path.write_text("\n".join(out), encoding="utf-8")
    return changed


def edit_learning(name: str, old_text: str, new_text: str) -> bool:
    new_text = " ".join((new_text or "").split())
    if not new_text:
        return False
    done = []

    def fn(ts, text):
        if not done and text == old_text:
            done.append(1)
            return new_text
        return None
    return _rewrite(name, fn)


def archive_learning(name: str, old_text: str) -> bool:
    done = []

    def fn(ts, text):
        if not done and text == old_text:
            done.append(1)
            return ""
        return None
    return _rewrite(name, fn)


def remove_last_learning_starting(name: str, prefix: str) -> bool:
    """Karar geri alınınca o karardan yazılmış son öğrenilen satırı kaldırır."""
    path = skill_path(name)
    if not path:
        return False
    texts = [m.group(2) for l in path.read_text(encoding="utf-8").split("\n") if (m := _ENTRY.match(l))]
    match = next((t for t in reversed(texts) if t.startswith(prefix)), None)
    return archive_learning(name, match) if match else False
