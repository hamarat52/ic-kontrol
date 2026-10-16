from app import config, skills


def test_seed_copied_only_when_missing(env):
    target = config.SKILLS_DIR / "kontrol-metrikleri.md"
    target.unlink()
    skills.ensure_seed()
    assert target.exists()

    skills.append_learning("kontrol-metrikleri", "Kullanıcının öğrendiği kural")
    skills.ensure_seed()  # tekrar çağrı öğrenileni silmemeli
    assert "Kullanıcının öğrendiği kural" in target.read_text(encoding="utf-8")


def test_seed_files_are_pristine():
    for f in skills.SEED_DIR.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        assert "## Öğrenilenler" in text
        after = text.split("## Öğrenilenler", 1)[1]
        assert "- [" not in after, f"{f.name} içinde kullanıcı verisi var"
