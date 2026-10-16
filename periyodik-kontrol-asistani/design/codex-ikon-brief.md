# Codex İkon Brief'i — Periyodik Kontrol Asistanı

Görevin yalnız bu uygulamanın **ikonlarını tasarlamak**. Kod, arayüz veya başka dosyaya
dokunma. Çıktıları yalnız `static/icons/src/` klasörüne yaz.

Referans görseller (stil kaynağı):
- `design/referans/ref-ikon-seti.jpg` — Okul / Tatil / İş / Alışveriş: yumuşak 3D nesneler.
- `design/referans/ref-belge-kalem.jpg` — katmanlı belge + kalem.

## 1. Stil kuralları (bütün ikonlar için ortak)

- **Materyal:** pürüzsüz, yumuşak 3D; hafif parlak plastik / kil (clay) hissi. Kenarlar
  yuvarlatılmış pahlı. Çizgi (outline) **yok**, derinlik ton ve ışıkla verilir.
- **Işık:** ana ışık sol üstten, yumuşak dolgu ışığı sağdan. Tek, yumuşak bir parlama
  (specular) noktası. Sert yansıma yok.
- **Kamera:** önden, ~10° yukarıdan, nesne ~15° hafif 3/4 dönük. Bütün sette aynı.
- **Arka plan:** tamamen **şeffaf**. Zemine düşen gölge, beyaz kart veya squircle tile
  **ekleme** — tile'ı ve gölgeyi uygulama CSS ile yapıyor.
- **Okunurluk:** ikon 20px'te de tanınmalı. Basit siluet, en fazla 2–3 parça, ince detay yok.
- **Yazı:** hiçbir ikonda yazı yok. Tek istisna Word'de tek harf "W", Excel'de tek harf "X".
  Gerçek Microsoft logosu kullanma.
- **Palet** (dışına çıkma):
  - Mavi `#4C8DF6` · Yeşil `#3DBE7A` · Turuncu `#F59E42` · Mercan `#F0605D`
  - Sarı `#FFC93C` · Mor `#8B7CF6` · Koyu gri `#2B2D35` · Kırık beyaz `#F7F6F3`
- **His:** sakin, premium, sevimli ama çocukça değil. Bankacılık iç kontrol uygulamasına
  yakışmalı.

## 2. Teslim formatı

- Her ikon: **1024×1024 PNG, şeffaf arka plan**, nesne kenarlardan ~%10 boşluklu ve ortalı.
- Dosya adı: aşağıdaki tablodaki `dosya` sütunu (ör. `belgeler.png`).
- Konum: `periyodik-kontrol-asistani/static/icons/src/`.
- Küçültme / WebP dönüşümünü uygulama tarafı yapacak; sen yalnız master PNG üret.
- Bitince her dosyayı listeleyen kısa bir `static/icons/src/LISTE.md` yaz (dosya adı + bir
  cümle açıklama).

## 3. İkon listesi (18 adet)

### Gezinme (sidebar)
| dosya | nesne | renk |
|---|---|---|
| `belgeler.png` | üst üste 2–3 belge sayfası, ön sayfada birkaç satır | beyaz sayfalar, mavi vurgu |
| `kontrol-setleri.png` | klipsli pano (clipboard), üzerinde 3 onay kutulu satır | turuncu pano, beyaz kâğıt, yeşil tikler |
| `kutuphane.png` | yan yana dizili 3 klasör/cilt, biri hafif eğik | mavi, yeşil, sarı ciltler |
| `bilgi-tabani.png` | yumuşak ampul, içinde küçük parıltı | sarı ampul, koyu gri duy |
| `ayarlar.png` | tek dişli çark, ortası delik | koyu gri, hafif mavi parlama |

### Kontrol kategorileri
| dosya | nesne | renk |
|---|---|---|
| `kat-operasyonel.png` | iç içe geçmiş 2 dişli | turuncu + koyu gri |
| `kat-mevzuat.png` | adalet terazisi | mor |
| `kat-bilgi-sistemleri.png` | kalkan, ortasında anahtar deliği | mavi kalkan, beyaz delik |
| `kat-finansal.png` | 3 yükselen sütun grafik | yeşil sütunlar, beyaz taban |
| `kat-aml.png` | büyüteç, arkasında üst üste 2 madeni para | mercan büyüteç sapı, sarı paralar |

### Aksiyonlar
| dosya | nesne | renk |
|---|---|---|
| `yukle.png` | açık tepsi, içinden yukarı çıkan yuvarlak ok | mavi ok, beyaz tepsi |
| `uret.png` | sihirli değnek + 2 küçük yıldız parıltı | koyu gri değnek, sarı yıldızlar |
| `word.png` | belge sayfası, sol üstünde mavi kare içinde "W" | beyaz sayfa, mavi kare |
| `excel.png` | belge sayfası, ızgara çizgili, sol üstünde yeşil kare içinde "X" | beyaz sayfa, yeşil kare |
| `yeni-set.png` | klipsli pano + sağ altta yuvarlak "+" rozet | turuncu pano, yeşil rozet |

### Boş durum çizimleri (daha detaylı olabilir, 160px'te gösterilecek)
| dosya | nesne | renk |
|---|---|---|
| `bos-belge.png` | açık boş klasör, üstünde süzülen tek sayfa | sarı klasör, beyaz sayfa |
| `bos-set.png` | boş klipsli pano, yanında sihirli değnek | turuncu pano, sarı parıltı |
| `bos-kutuphane.png` | boş raf, üzerinde tek devrilmiş cilt | koyu gri raf, mavi cilt |

## 4. Görüntü modeli kullanırsan prompt şablonu

Ortak stil eki (her promptun sonuna):

> soft 3D icon, smooth glossy clay material, rounded beveled edges, no outlines,
> soft key light from top-left, gentle fill light from right, single soft specular
> highlight, front view slightly from above, object rotated 15 degrees, centered with
> 10% padding, transparent background, no ground shadow, no text, minimal detail,
> readable at 20px, calm premium style, palette #4C8DF6 #3DBE7A #F59E42 #F0605D
> #FFC93C #8B7CF6 #2B2D35 #F7F6F3

Örnek: `a clipboard with three checkbox rows and green check marks, orange board, white
paper` + ortak stil eki.

## 5. Kabul ölçütleri

- 18 dosyanın hepsi var, adlar birebir doğru, 1024×1024, şeffaf.
- Yan yana konduğunda aynı setten çıktıkları belli (ışık, kamera, materyal, palet aynı).
- 20px'e küçültüldüğünde her biri ayırt edilebiliyor.
- Hiçbirinde zemin gölgesi, arka plan kartı veya fazladan yazı yok.

## Kapsam dışı (Codex yapmayacak)

Onay işareti, çarpı, ok, yıldız, ⋮, arama gibi küçük arayüz işaretleri uygulamada tek renk
çizgi ikon olarak kalacak; bunlar 3D değil ve bu brief'in parçası değil.
