# Teknik Karar

## Teknik Karar
- Backend: Python + FastAPI, tek process, `uvicorn` ile çalışır.
- Frontend: build adımı olmayan düz HTML/CSS/JS (`static/`), FastAPI tarafından statik servis edilir.
- Depolama: SQLite (`data/app.db`) + yerel dosya sistemi (`data/uploads/`, `data/skills/`).
- AI çağrısı: OpenAI-uyumlu HTTP endpoint (`httpx` ile), `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`
  ortam değişkenleriyle yapılandırılır. Varsayılan `http://localhost:11434/v1` (Ollama).
- Skill dosyaları: `data/skills/*.md`, Hermes skill mantığına benzer — statik başlangıç bilgisi +
  kullanım/geri bildirimle büyüyen bölüm.

## Neden
- Şirket Windows makinelerinde ayrı bir build zinciri olmadan çalışmalı → build'siz frontend.
- FastAPI, PDF/DOCX ayrıştırma ve ileride PM4Py/ML eklemeye uygun Python ekosistemine sahip.
- SQLite: ek DB sunucusu kurulumu gerektirmiyor, tek dosya, taşınabilir.
- Gerçek banka verisi bu ortama hiç girmeyecek (kullanıcı kararı) — kod işyerinde sentetik/anonim
  veriyle ve lokal modelle test edilecek; bu yüzden AI çağrısı en baştan configurable.

## Alternatifler
- Node.js/Express: reddedildi — Python'un ML/doküman işleme kütüphane ekosistemi bu proje için
  daha uygun (ileride PM4Py, embedding, vb. eklenebilir).
- Vektör DB (Chroma/Pinecone vb.): şimdilik reddedildi — doküman hacmi küçük, basit TF benzeri
  / brute-force arama yeterli; gerçek veri ölçeği görülünce yeniden değerlendirilir.

## Not Edilecekler
- Çalıştırma: `cd periyodik-kontrol-asistani && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8077`
- Ortam değişkenleri (opsiyonel, yoksa varsayılan kullanılır):
  - `LLM_BASE_URL` (varsayılan `http://localhost:11434/v1`)
  - `LLM_MODEL` (varsayılan `llama3.1`, işyerinde gerçek model adıyla değiştirilmeli)
  - `LLM_API_KEY` (varsayılan `local`, çoğu lokal sunucu için gerekmez)
- Gerçek/hassas banka verisi bu repoya veya bu makineye hiçbir şekilde yüklenmez.
- `data/uploads/` ve `data/app.db` `.gitignore` ile dışarıda; yalnız `data/skills/` seed
  içerikleri commit edilir (gerçek şirket verisi içermez, genel/kamuya açık bilgi).
