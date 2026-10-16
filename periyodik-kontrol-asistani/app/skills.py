"""Skill dosyalarını okuma ve geri bildirimle güncelleme.

Hermes skill mantığına benzer: her skill bir markdown dosyası, "Öğrenilenler"
bölümü kullanım/geri bildirim arttıkça büyür. Şimdilik güncelleme kural
tabanlı (LLM olmadan da çalışır); LLM varsa daha nitelikli özetleme için
kullanılabilir (bkz. llm.summarize_feedback_for_skill).
"""
from datetime import datetime
from pathlib import Path

from . import config


def list_skills() -> list[dict]:
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
