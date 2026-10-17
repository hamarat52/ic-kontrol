from app import retrieval as R

MEVZUAT = """YÖNETMELİK BİRİNCİ BÖLÜM
Amaç

MADDE 1 – (1) Bu Yönetmeliğin amacı bankaların bilgi sistemlerinin yönetimidir.
Kimlik ve erişim yönetimi

MADDE 11 – (1) Banka, kullanıcı erişim yetkilerini en az yılda bir gözden geçirir.
(2) Ayrıcalıklı hesapların kullanımı kayıt altına alınır ve izlenir.
İş sürekliliği

MADDE 13 – (1) Banka iş sürekliliği planını yılda bir test eder.
GEÇİCİ MADDE 1 – (1) Mevcut sistemler bir yıl içinde uyumlu hale getirilir.
"""

STANDART = """1. Introduction
Operational risk is inherent in all banking products.

Principle 2: Banks should develop and maintain a framework for operational risk.
The framework should be documented and approved by the board of directors.

3. Business continuity
Banks should have business continuity plans tested periodically and kept up to date.
"""


def test_mevzuat_madde_basliklari():
    ps = R.split_pieces(MEVZUAT)
    labels = [p["label"] for p in ps]
    assert labels[0] == "Madde 1 — Amaç"
    assert "Madde 11 — Kimlik ve erişim yönetimi" in labels
    assert any(l.startswith("Geçici Madde 1") for l in labels)


def test_madde_yapisi_olmayan_belge_basliga_gore_bolunur():
    ps = R.split_pieces(STANDART * 6)
    assert len(ps) >= 2
    assert all(p["text"] for p in ps)


def test_arama_ilgili_maddeyi_bulur_ve_ekleri_tolere_eder():
    ix = R.Index([{"id": "m", "ad": "BS Yönetmeliği", "text": MEVZUAT},
                  {"id": "s", "ad": "BCBS", "text": STANDART}])
    hits = ix.search("Kullanıcıların erişim yetkileri yıllık olarak gözden geçirilmeli; ayrıcalıklı hesaplar izlenmeli")
    assert hits and hits[0]["label"].startswith("Madde 11")
    hits = ix.search("İş sürekliliği planlarının periyodik testi")
    assert {h["doc_id"] for h in hits} >= {"m"}


def test_arama_butceyi_ve_belge_basina_siniri_asmaz():
    long = "\n\n".join(f"MADDE {i} – (1) erişim yetkisi gözden geçirme kuralı {i}." for i in range(1, 30))
    ix = R.Index([{"id": "a", "ad": "A", "text": long}])
    hits = ix.search("erişim yetkisi gözden geçirme", k=6, budget=10_000)
    assert len(hits) <= 2


def test_bos_sorgu_ve_bos_dizin():
    assert R.Index([]).search("herhangi") == []
    assert R.format_block([], "X") == ""
