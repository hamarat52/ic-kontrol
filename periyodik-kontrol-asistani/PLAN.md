# Periyodik Kontrol Asistanı — Geliştirme Planı

Amaç: işyerinde, internetsiz, yerel modelle; onlarca uzun "uygulama esası" belgesinden
güvenilir, izlenebilir periyodik kontrol önerisi üreten ve kullanıldıkça iyileşen bir araç.

## Mevcut durumun açıkları (öncelik sırasıyla)

1. **Belge ölçeği:** Tüm belgeler birleştirilip ilk ~14.000 karakter modele veriliyor; geri kalanı
   **sessizce yok sayılıyor**. Gerçek uygulama esasları yüzlerce sayfa. En kritik açık bu.
2. **İzlenebilirlik:** Modelin verdiği "kaynak alıntısı" doğrulanmıyor; uydurma olabilir.
   Hangi belgenin hangi bölümünden geldiği tutulmuyor. Denetimde kanıt zinciri şart.
3. **Öneri kalitesi:** 7B modelde kontrollerin %90'ı "Operasyonel / Hat 2". Kategori ve hat
   tanımları prompt'ta yok; tekrar eden kontroller ayıklanmıyor.
4. **Öğrenme döngüsü:** Kabul edilen kontroller (kütüphane) ve reddedilenler yeni üretimde
   kullanılmıyor. Bilgi tabanı sınırsız büyüyor, kullanıcı yanlış öğrenileni silemiyor.
5. **İşyerine kurulum:** Model adresi yalnız ortam değişkeniyle değişiyor; Windows başlatma
   betiği, BT için kurulum notu, arayüzden bağlantı testi yok.
6. **Test altyapısı:** Otomatik test yok; her şey elle ve gerçek modelle deneniyor.

## Adımlar

| # | Adım | Kabul ölçütü |
|---|---|---|
| 0 | Test altyapısı: sahte (deterministik) OpenAI-uyumlu model sunucusu + pytest | Mevcut uç noktalar modelsiz test edilebiliyor, testler yeşil |
| 1 | Belgeleri bölümlere ayırıp tek tek işleme, ilerleme gösterimi, kaynak (belge + bölüm) takibi, alıntı doğrulama, tekrar ayıklama | 50+ sayfalık sentetik belge setinde hiçbir bölüm atlanmıyor; uydurma alıntı işaretleniyor; testler yeşil |
| 2 | Öneri kalitesi: kategori/hat tanımları, kütüphaneden örnek, reddedilenlerden kaçınma | Aynı sentetik sette kategori dağılımı öncekinden belirgin dengeli (ölçülür) |
| 3 | Öğrenme döngüsü kontrolü: öğrenilen kuralı silme/düzenleme, bilgi tabanını derleme, prompt bütçesi | Kural silinince bir sonraki üretimde kullanılmıyor; bilgi tabanı bütçeyi aşmıyor |
| 4 | Ayarlar sayfası (model adresi, model seçimi, bağlantı testi) + Windows başlatma betiği + BT kurulum notu | Arayüzden model değişip test edilebiliyor; `baslat.bat` ile tek tıkla açılıyor |
| 5 | Performans ve son cila: 150+ kontrolde akıcılık, açılış süresi ölçümü | Ölçümler raporlanır; 150 kontrolde liste çizimi < 50 ms |

Her adım: uygula → otomatik test → gerçek yerel modelle bir deneme → commit → kısa rapor.

## Kapsam dışı (şimdilik)

- 3D ikon üretimi (Codex'e verilecek, kullanıcı isteyince).
- Çok kullanıcılı yetkilendirme, sunucu kurulumu.

## Dağıtım kararı (kullanıcı)
- İşyerinde **tek sunucuya (on-prem)** kurulacak, kullanıcılar tarayıcıdan URL ile erişecek. Masaüstü başlatıcı (`baslat.bat`) gerekmiyor.
- Sonuçları: çok kullanıcılı kullanım → kullanıcı kimliği (USER.md kişiye özel, kim neyi kabul/ret etti izi), sunucunun ağa açılması (host/port ayarı), aynı anda tek üretim kuyruğu, sunucu tarafında yedekleme.
- Açık: kimlik doğrulama yöntemi (kurum AD/SSO mu, uygulama içi basit giriş mi).
