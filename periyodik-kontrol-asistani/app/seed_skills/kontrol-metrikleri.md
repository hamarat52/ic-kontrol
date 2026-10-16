# Skill: Kontrol Önerisi Metrikleri (Kategori / Sıklık / Risk / Efor)

> Seed bilgisi — her periyodik kontrol önerisi bu dört metrikle birlikte üretilmelidir.

## Kategori (örnek taksonomi, belgeye göre genişletilebilir)
- Operasyonel kontrol (işlem/şube düzeyinde)
- Mevzuat uyum kontrolü (BDDK/MASAK/TCMB)
- Bilgi sistemleri / erişim kontrolü (yetki, SOD — görevler ayrılığı)
- Finansal raporlama kontrolü
- AML / Şüpheli İşlem (MASAK ŞİB) kontrolü

## Sıklık
- Anlık / sürekli (continuous monitoring) — yüksek hacimli, otomatikleştirilebilir işlemler için.
- Günlük, haftalık, aylık, üç aylık, yıllık — işlem hacmi ve risk düzeyine göre seçilir.
- Olay tetiklemeli (event-triggered) — örn. yeni mevzuat yayımı, personel değişikliği.

## Risk (düşük / orta / yüksek / kritik)
Değerlendirme kriterleri:
- Finansal etkinin büyüklüğü (maddi hata/zarar potansiyeli)
- Yasal/cezai sonuç potansiyeli (özellikle MASAK — tipping-off ihlali ceza hukuku suçudur)
- Geçmiş bulgu sıklığı (aynı alanda tekrarlayan zafiyet varsa risk yükseltilir)
- İtibar riski

## Efor (düşük / orta / yüksek)
- Mevcut otomasyon/veri erişimi var mı? (Varsa efor düşer)
- Manuel örneklem mi, sistem sorgusu mu gerektiriyor?
- Kaç birimin/sistemin koordinasyonunu gerektiriyor?

## Çıktı formatı (öneri başına)
```
Kontrol adı:
Kategori:
Ait olduğu hat (1/2/3):
Sıklık:
Risk:
Efor:
Gerekçe / dayanak (belge referansı veya mevzuat maddesi):
```

## Öğrenilenler
_(henüz geri bildirim yok — kullanım arttıkça buraya eklenir)_
