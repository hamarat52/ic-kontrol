# İç Kontrol Projeleri

Kurumsal işyeri için web tabanlı araçlar ve otomasyonlar. Bu repo, `ickontrol`
Hermes profilinin kendi çalışma alanıdır; Yusuf'un kişisel OBS/Projeler
ağacından tamamen ayrıdır.

## Kurallar
- Her araç tarayıcı tabanlı çalışır (HTML/JS veya yerel web sunucusu) —
  işyerindeki Windows makinelerde de ayrı bir build gerekmeden çalışsın diye.
- Üründeki çalışma zamanı AI özellikleri, sabit bir bulut API anahtarına değil,
  yapılandırılabilir bir yerel LLM uç noktasına (Ollama / LM Studio / vLLM,
  OpenAI-uyumlu API) bağlanır — ortam değişkeni veya config dosyası üzerinden.
- Secrets, token, `.env` bu repoya girmez.

## Yapı
Her araç/otomasyon kendi alt klasöründe. Alt klasöre kısa bir README ile ne
işe yaradığı, çalıştırma komutu ve varsa test komutu eklenir.
