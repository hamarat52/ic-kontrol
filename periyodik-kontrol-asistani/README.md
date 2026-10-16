# Periyodik Kontrol Asistanı

Şirket içi süreç/prosedür belgelerini yükleyip "Periyodik Kontrolleri Çıkart" dediğinde,
kamuya açık denetim/iç kontrol bilgisi ve kendi biriktirdiği skill'leri kullanarak periyodik
kontrol önerileri (kategori, sıklık, risk, efor) üreten web uygulaması. Öneriler üzerinde
verilen geri bildirim (kabul/red/düzenle) skill dosyalarını güncelleyerek sistemi zamanla
geliştirir.

Teknik kararlar ve çalıştırma komutu için `TECH.md`.

## Durum
İskelet / ilk sürüm. AI çağrısı gerçek bir OpenAI-uyumlu endpoint'e (varsayılan Ollama,
`http://localhost:11434/v1`) bağlanacak şekilde yazıldı; bu geliştirme ortamında lokal model
olmadığı için uçtan uca öneri üretimi henüz işyerinde test edilmedi — bağlantı hatası durumunda
uygulama çökmez, açık bir hata mesajı döner.

## Hızlı başlangıç
```
cd periyodik-kontrol-asistani
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8077
```
Tarayıcıda `http://localhost:8077` aç.
