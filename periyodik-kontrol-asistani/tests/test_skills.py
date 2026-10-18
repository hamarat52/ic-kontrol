"""Öğrenen yapı: konular, onay kapısı, tercihler, dosya çıktısı, dışa aktarma, kararlardan kural."""
import io
import json
import zipfile

from app import config, ogrenme, skills, storage
from conftest import jsonl, wait_set


def test_seed_files_are_standard_and_pristine():
    for f in skills.SEED_DIR.glob("*/SKILL.md"):
        text = f.read_text(encoding="utf-8")
        assert text.startswith("---\nname: " + f.parent.name + "\ndescription: ")
        assert "## Öğrenilenler" not in text, f"{f} içinde kullanıcı verisi var"
    assert not list(skills.SEED_DIR.glob("*.md"))


def test_legacy_flat_files_migrated(env):
    (config.SKILLS_DIR / "kontrol-metrikleri.md").write_text(
        "# Skill\n\n## Öğrenilenler\n- [2026-10-16 21:23] Gerekçe kısa olsun.\n"
        "- [2026-10-16 21:24] Reddedildi: 'X' (Operasyonel, Aylık, risk Orta).\n", encoding="utf-8")
    skills.ensure_seed()
    with storage.db_session() as conn:
        rows = {r["metin"]: r["durum"] for r in conn.execute("SELECT metin, durum FROM learnings")}
    assert rows == {"Gerekçe kısa olsun.": "onayli", "Reddedildi: 'X' (Operasyonel, Aylık, risk Orta).": "arsiv"}
    assert not (config.SKILLS_DIR / "kontrol-metrikleri.md").exists()
    md = (config.SKILLS_DIR / "kontrol-metrikleri" / "SKILL.md").read_text(encoding="utf-8")
    assert md.startswith("---\nname: kontrol-metrikleri") and "- Gerekçe kısa olsun." in md and "Reddedildi" not in md
    skills.ensure_seed()      # ikinci çağrı tekrar taşımaz
    with storage.db_session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 2


def test_approval_gate_and_prompt_scope(client, env):
    with storage.db_session() as conn:
        a = skills.propose(conn, "masak-aml", "Şüpheli işlem kontrollerinde bildirim süresi 10 gün esas alınır.", "sohbet")
        b = skills.propose(conn, "kredi", "Teminat değerleme kontrolleri altı aydan sık olmasın.", "sohbet")
        assert skills.propose(conn, "kredi", "Teminat değerleme kontrolleri altı aydan sık olmasın.", "sohbet") is None
    assert "10 gün esas" not in skills.read_skills_text()               # onaysız kural modele gitmez
    r = client.post(f"/api/learnings/{a}/decision", json={"karar": "onayla"})
    assert r.status_code == 200
    assert client.post(f"/api/learnings/{a}/decision", json={"karar": "at"}).status_code == 409
    client.post(f"/api/learnings/{b}/decision", json={"karar": "onayla", "metin": "Teminat değerlemesi yıllık; kontrol altı ayda bir."})
    # alan kapsamı: Kredi setinde AML konusu girmez, genel konular girer
    kredi = skills.read_skills_text(["Kredi"])
    assert "Teminat değerlemesi yıllık" in kredi and "10 gün esas" not in kredi and "Kontrol Metrikleri" in kredi
    assert "10 gün esas" in skills.read_skills_text(["AML / Uyum"])
    # dosyalar standart biçimde yazıldı
    md = (config.SKILLS_DIR / "kredi" / "SKILL.md").read_text(encoding="utf-8")
    assert md.startswith("---\nname: kredi\n") and "alanlar: [\"Kredi\"]" in md
    ov = client.get("/api/learnings").json()
    assert not ov["bekleyen"] and any(k["name"] == "kredi" and k["learnings"] for k in ov["konular"])
    lid = next(k for k in ov["konular"] if k["name"] == "kredi")["learnings"][0]["id"]
    assert client.patch(f"/api/learnings/{lid}", json={"metin": "Yeni metin."}).status_code == 200
    assert client.delete(f"/api/learnings/{lid}").status_code == 200
    assert "Yeni metin" not in skills.read_skills_text(["Kredi"])
    assert client.post("/api/learnings/9999/decision", json={"karar": "onayla"}).status_code == 404
    assert client.post("/api/learnings", json={"karar": "onayla", "skill": "yok", "metin": "x"}).status_code == 400
    assert client.post("/api/learnings", json={"karar": "onayla", "skill": "kontrol-metrikleri", "metin": "Elle kural."}).status_code == 200
    assert "Elle kural." in skills.read_skills_text(["Kredi"])


def test_prefs_budget_and_user_md(client, env):
    assert client.post("/api/prefs", json={"metin": "Gerekçe en fazla iki cümle."}).status_code == 200
    assert "Gerekçe en fazla iki cümle." in (config.DATA_DIR / "USER.md").read_text(encoding="utf-8")
    assert "Kullanıcı tercihleri" in skills.read_skills_text(["Kredi"])
    assert client.post("/api/prefs", json={"metin": "x" * 1500}).status_code == 400
    pid = client.get("/api/learnings").json()["tercihler"][0]["id"]
    assert client.patch(f"/api/prefs/{pid}", json={"metin": "  "}).status_code == 400
    assert client.patch(f"/api/prefs/{pid}", json={"metin": "Gerekçe tek cümle."}).status_code == 200
    client.delete(f"/api/prefs/{pid}")
    assert client.get("/api/learnings").json()["tercihler"] == []


def test_export_zip(client, env):
    client.post("/api/prefs", json={"metin": "Kısa yaz."})
    client.post("/api/learnings", json={"karar": "onayla", "skill": "masak-aml", "metin": "AML kuralı."})
    r = client.get("/api/learnings/export")
    assert r.status_code == 200 and ".zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"USER.md", "BENIOKU.md", "masak-aml/SKILL.md", "genel-cerceve/SKILL.md"} <= names
    assert "- AML kuralı." in z.read("masak-aml/SKILL.md").decode()
    assert "Kısa yaz." in z.read("USER.md").decode()
    z2 = zipfile.ZipFile(io.BytesIO(client.get("/api/learnings/export?baslangic=0").content))
    assert "genel-cerceve/SKILL.md" not in z2.namelist() and "masak-aml/SKILL.md" in z2.namelist()


def test_rejections_become_one_pending_rule(client, env):
    client.post("/api/documents", files={"file": ("p.txt", "1. A\nmetin burada\n".encode(), "text/plain")})
    names = ["Rol çakışması kontrolü", "Yetki matrisi gözden geçirmesi", "Erişim talebi onayı", "Log incelemesi"]
    env.responder = lambda m, stream: jsonl(*[{"tip": "kontrol", "kontrol_adi": x, "kategori": "Bilgi Sistemleri",
                                               "sorumlu": "Bilgi Güvenliği"} for x in names]) if stream else "{}"
    s = wait_set(client, client.post("/api/sets").json()["id"])
    ids = [c["id"] for c in s["controls"]]
    seen = {}

    def responder(m, stream):
        seen["user"] = m[-1]["content"]
        return json.dumps({"kural": "Görevler ayrılığı kontrollerinde sorumlu iş biriminin yöneticisidir.",
                           "gerekce": "Üç retin hepsinde sorumlu Bilgi Güvenliği yazıyordu."}, ensure_ascii=False)
    env.responder = responder
    client.post(f"/api/controls/{ids[0]}/decision", json={"karar": "red"})
    client.post(f"/api/controls/{ids[1]}/decision", json={"karar": "red"})
    client.post(f"/api/controls/{ids[1]}/decision", json={"karar": "bekliyor"})   # geri alınan ret sayılmaz
    with storage.db_session() as conn:
        assert len(ogrenme.pending_events(conn, s["id"])) == 1
    client.post(f"/api/controls/{ids[2]}/decision", json={"karar": "red"})
    client.patch(f"/api/controls/{ids[3]}", json={"sorumlu": "BT Operasyon"})
    lid = ogrenme.analyze(s["id"])          # eşzamanlı çalıştır (arka plan iş parçacığı da tetiklenmiş olabilir)
    ov = client.get("/api/learnings").json()
    assert len(ov["bekleyen"]) == 1
    p = ov["bekleyen"][0]
    assert "sorumlu iş biriminin yöneticisidir" in p["metin"] and p["kaynak"] == "kararlar" and "2 ret" in p["neden"]
    assert "Rol çakışması" in seen["user"] and "BT Operasyon" in seen["user"]
    assert ogrenme.analyze(s["id"]) is None and lid in (None, p["id"])  # olaylar incelendi olarak işaretlendi
    assert "Reddedildi" not in skills.read_skills_text()


def test_chat_rule_topic_from_source_document_area(client, env):
    d = client.post("/api/documents", files={"file": ("Kredi Tahsis Uygulama Esasları.txt",
        "1. Teminat\nKredi teminatı değerlenir; kredi tahsis komitesi onaylar.\n".encode(), "text/plain")}).json()
    assert d["alanlar"][0] == "Kredi"
    env.responder = lambda m, stream: jsonl({"tip": "kontrol", "kontrol_adi": "Teminat değerleme"}) if stream else "{}"
    s = wait_set(client, client.post("/api/sets").json()["id"])
    cid = s["controls"][0]["id"]
    env.responder = lambda m, stream: json.dumps({"yanit": "Tamam.", "degisiklikler": [],
                                                  "ders": "Teminat değerleme kontrolleri altı aydan sık olmasın."})
    r = client.post(f"/api/sets/{s['id']}/chat", json={"message": "sık", "control_id": cid}).json()
    assert r["message"]["learning"]["skill"] == "kredi"


def test_deferred_analysis_runs_after_generation(client, env):
    from app import jobs
    client.post("/api/documents", files={"file": ("p.txt", "1. A\nmetin burada\n".encode(), "text/plain")})
    env.responder = lambda m, stream: jsonl(*[{"tip": "kontrol", "kontrol_adi": f"K{i}"} for i in range(3)]) if stream else "{}"
    s = wait_set(client, client.post("/api/sets").json()["id"])
    real = jobs.is_running
    jobs.is_running = lambda: "baska-set"                               # üretim sürüyormuş gibi
    try:
        for c in s["controls"]:
            client.post(f"/api/controls/{c['id']}/decision", json={"karar": "red"})
        import time
        time.sleep(0.3)
        with storage.db_session() as conn:
            assert len(ogrenme.pending_events(conn, s["id"])) == 3      # ertelendi
    finally:
        jobs.is_running = real
    env.responder = lambda m, stream: json.dumps({"kural": "Genel kural.", "gerekce": "g"})
    ogrenme.analyze_backlog()
    assert [b["metin"] for b in client.get("/api/learnings").json()["bekleyen"]] == ["Genel kural."]


def test_chat_splits_general_and_area_rules(client, env):
    client.post("/api/documents", files={"file": ("Kredi Tahsis Uygulama Esasları.txt",
        "1. Teminat\nKredi teminatı değerlenir; kredi tahsis komitesi onaylar.\n".encode(), "text/plain")})
    env.responder = lambda m, stream: jsonl({"tip": "kontrol", "kontrol_adi": "Teminat değerleme"}) if stream else "{}"
    s = wait_set(client, client.post("/api/sets").json()["id"])
    cid = s["controls"][0]["id"]
    env.responder = lambda m, stream: json.dumps({"yanit": "Onaylarsan uygularım.", "degisiklikler": [], "dersler": [
        {"kural": "Hat 3 kontrolleri sete girmez.", "genel": True},
        {"kural": "Teminat değerleme kontrolleri aylık önerilmez.", "genel": False}]}, ensure_ascii=False)
    m = client.post(f"/api/sets/{s['id']}/chat", json={"message": "x", "control_id": cid}).json()["message"]
    assert [(l["skill"], l["durum"]) for l in m["learnings"]] == [("genel-cerceve", "bekliyor"), ("kredi", "bekliyor")]
    again = client.get(f"/api/sets/{s['id']}").json()["messages"][-1]
    assert len(again["learnings"]) == 2
