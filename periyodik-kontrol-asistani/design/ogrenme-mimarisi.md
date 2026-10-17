# Öğrenen Bilgi Tabanı — Hermes incelemesi ve öneri

Durum: **TASLAK — kullanıcı onayı bekliyor.** Kod yazılmadı.

## 1. Hermes nasıl yapıyor (incelenen: resmi dokümanlar + bu profilin `skills/` klasörü)

### Katmanlar — her dosyanın tek bir işi var
| Katman | İçerik | Kim yazar | Prompt'a ne zaman girer | Sınır |
|---|---|---|---|---|
| SOUL.md | Kimlik, ton | İnsan | Her oturum, en başta | — |
| AGENTS.md | Proje kuralları | İnsan | Oturum başında, çalışma klasöründen | — |
| MEMORY.md / USER.md | Kısa, her zaman gerekli gerçekler | Ajan (`memory` aracı) | Oturum başında **dondurulmuş kopya** | 2.200 / 1.375 karakter |
| Skill'ler (`SKILL.md`) | Konu bazlı prosedür + dersler | Ajan (`skill_manage`) ve insan | **Yalnız ilgiliyse** (önce ad+açıklama listesi, sonra içerik) | Dosya başına yok; katalog küçük tutulur |
| Oturum geçmişi | Ham konuşmalar | Otomatik | Hiç; gerekince aranır (SQLite FTS) | Sınırsız |

### Yazma
- **Ön planda:** ajan iş sırasında bir şey öğrenince aracı çağırarak yazar (add / patch / remove).
- **Arka plan incelemesi:** her turdan sonra ayrı bir model çatalı konuşmayı yeniden okur, "kalıcı ders var mı?" diye bakar, varsa skill/memory'yi günceller. İsteğe bağlı olarak daha ucuz bir modelde çalışır.
- **Kural: "ders yaz, kayıt yazma".** Bir girdi genellenebilir bir kural + tek cümlelik nedenidir. Tarih, olay anlatımı, alıntı skill içeriği değildir.
- **Sınır dolunca otomatik kırpma yok:** yazma reddedilir, ajan aynı turda girdileri birleştirip yer açmak zorundadır. Prompt boyutu sınırlı kalır.
- **Onay kapısı (`write_approval`):** açılırsa her yazma bekletilir; insan `onayla / reddet` der, fark (diff) görülebilir.
- **Güvenlik taraması:** prompt'a girecek her yazı enjeksiyon / sızdırma kalıplarına karşı taranır.

### Bakım (Curator)
- Her skill için kullanım sayaçları tutulur (`.usage.json`: görüntülenme, kullanım, yama sayısı, son kullanım, durum, sabitlenmiş mi).
- Kullanılmayan skill `aktif → bayat (30 gün) → arşiv (90 gün)` olur. **Asla silinmez**, arşivden geri alınır.
- Her bakım öncesi tüm klasörün yedeği alınır; tek komutla geri dönülür.
- Her değişiklik bir defterde (`.curator_ledger.jsonl`) önce/sonra özetiyle durur; tek değişiklik geri alınabilir.
- İsteğe bağlı LLM birleştirme: birbirine benzeyen dar skill'leri tek "şemsiye" skill'de toplar.
- Kaynak bilgisi: `created_by` (paketle gelen / ajan / hub). Paketle gelenler korunur.

### Görünürlük
- `/journey`: öğrenilen her şeyin zaman çizelgesi; buradan düzenle / sil (sil = arşivle).
- Ajan bir şey öğrenince sohbette `💾 Skill 'x' güncellendi` satırı.

## 2. Bizim uygulamada şu an
- 3 seed skill (`app/seed_skills`) → çalışma kopyası `data/skills/*.md`.
- Ret / düzeltme / sohbet sonucu dosyanın sonuna ham satır ekleniyor: `- [tarih] Reddedildi: '...'`. Bu bir **kayıt**, ders değil; zamanla şişer ve modele gürültü olur.
- Hangi skill'e yazılacağı kategoriye göre tahmin ediliyor (2 seçenek).
- Her set üretiminde **tüm** skill'ler prompt'a giriyor (yerel modelin bağlam penceresini doldurur).
- Silme, düzenleme, geri alma, onay, kullanım istatistiği yok.
- Kabul/ret geçmişi zaten veritabanında; üretime örnek olarak veriliyor (bu iyi, kalmalı).

## 3. Öneri: aynı ilkeler, iç kontrole uyarlanmış

### 3.1 Katmanlar
| Bizde | Hermes karşılığı | İçerik | Kim yazar |
|---|---|---|---|
| **Uygulama talimatı** (kodda) | SOUL | Kontrol nasıl yazılır, çıktı biçimi | Geliştirici |
| **Kurum Profili** | MEMORY/USER | Her üretimde gerekli kısa gerçekler: şube sayısı/hacmi, kullanılan sistemler, organizasyon adları, genel tercih ("operasyonel kontroller haftalıktan sık olmasın"). **~1.500 karakter sınırı.** | Sistem önerir, kullanıcı onaylar; kullanıcı doğrudan da yazar |
| **Konu skill'leri** | Skills | Süreç alanı başına bilgi + dersler: Kredi Tahsis, Ödeme/Transfer, Erişim Yönetimi, AML, … | Seed + sistem önerir + kullanıcı |
| **Karar geçmişi** | Oturum geçmişi | Her kabul/ret/düzenleme/sohbet, kaynak bölümüyle. Prompt'a girmez; benzer örnek gerekince aranır. | Otomatik |

### 3.2 Kullanım (prompt'a ne girer)
- Kurum Profili: her bölümde.
- Konu skill'leri: **yalnız o bölümle ilgili olan 1–2 tanesi** (bölüm metni ile skill açıklaması/anahtar kelimeleri eşleştirilir; LLM gerekmez). Yerel modelin bağlamı korunur.
- Karar geçmişi: o bölüme en çok benzeyen birkaç kabul/ret örneği (şu an yapılan, iyileştirilmiş hali).
- Set başlarken kullanılan profil + skill sürümü **dondurulur ve sete yazılır** → "Bu kontrol önerildiğinde hangi kurallar geçerliydi?" sorusu her zaman cevaplanır (denetim izi).

### 3.3 Öğrenme (yazma)
- Ham kayıtlar skill'e yazılmaz; veritabanında kalır.
- **Öğrenme incelemesi** (arka plan işi): bir set gözden geçirildikten sonra (ör. kararların çoğu verildiğinde ya da kullanıcı "bitti" dediğinde) model kararları + sohbeti okur, yapılandırılmış öneriler üretir:
  `{"islem":"ekle|guncelle|arsivle","hedef":"kurum-profili|<skill>","metin":"...","neden":"...","kanit":[karar id'leri]}`
- Öneriler **onay bekler** (Bilgi Tabanı'nda "Bekleyen öğrenmeler"): metin, neden ve kanıt (hangi kararlardan çıktı, tıklanınca o kontrole gider). Kullanıcı onaylar / düzenler / reddeder. Ayarlardan "otomatik uygula" açılabilir.
- Kurallar: ders yaz kayıt yazma; tek kural + tek cümle neden; çelişen eski dersi güncelle, yenisini ekleme.
- Sınır: profil ve her skill'in "dersler" bölümü için karakter bütçesi. Dolunca inceleme önce birleştirir.
- Güvenlik: yüklenen belgedeki metin ders olarak sızamaz — öneriler yalnız kullanıcı kararları ve sohbetinden üretilir; yazılar enjeksiyon kalıplarına karşı taranır.

### 3.4 Bakım
- Her ders için: kaç sette kullanıldı, o derslerle üretilen kontrollerin kabul oranı, son kullanım.
- Hiç kullanılmayan / kabul oranını düşüren dersler "gözden geçir" olarak işaretlenir. Otomatik silme yok; arşiv ve geri al.
- Her değişiklik defterde (kim, ne zaman, önce/sonra, kanıt) → tek tıkla geri al. Değişiklikten önce yedek.
- İsteğe bağlı birleştirme: benzer dersleri tek derste toplama önerisi (yine onaylı).

### 3.5 Saklama
- Kaynak: SQLite (`lessons`, `lesson_ledger`, `skill_versions`) — arayüzden düzenleme/onay/geri alma kolay.
- Her değişiklikte `data/skills/*.md` yeniden üretilir: insanlar okuyabilir, taşınabilir, dışa aktarılabilir (kurumlar arası paylaşım, yedek).

### 3.6 Arayüz (Bilgi Tabanı sayfası)
1. Kurum Profili (kısa kart, doluluk göstergesi: "1.120 / 1.500").
2. Bekleyen öğrenmeler (onay listesi, kanıt bağlantıları).
3. Konu skill'leri: başlangıç bilgisi + dersler; her derste kaynak, kullanım, düzenle / arşivle.
4. Geçmiş: değişiklik defteri, geri al.

## 4. Fazlar
1. **Veri modeli + arayüz:** `lessons` tablosu, defter, sete sürüm yazma, mevcut ham satırları içe alma, düzenle/arşivle/geri al, Kurum Profili.
2. **Seçici kullanım:** bölüme göre ilgili skill seçimi, bütçe.
3. **Öğrenme incelemesi:** yapılandırılmış öneriler + onay kuyruğu.
4. **Bakım:** kullanım/etki istatistikleri, gözden geçir işaretleri, birleştirme önerisi.

## Açık sorular
- Onay kapısı varsayılan açık mı olsun (önerilen) yoksa otomatik mi?
- Yeni konu skill'i açılabilsin mi (ör. "Hazine İşlemleri" belgesi gelince)? Önerilen: sistem önerir, kullanıcı onaylar.
- Tek kullanıcı mı, ekip mi aynı bilgi tabanını kullanacak? (Ekipse yazan kişi ve rol bilgisi gerekir.)
- ~~Sayfa adı~~ → karar: menü "Belgeler · Kontroller · Öğrenilenler".
