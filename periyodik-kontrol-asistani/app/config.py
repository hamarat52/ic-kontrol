import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Testler ve farklı kurulumlar için veri klasörü değiştirilebilir.
DATA_DIR = Path(os.environ.get("PKA_DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
SKILLS_DIR = DATA_DIR / "skills"
DB_PATH = DATA_DIR / "app.db"

# AI çağrısı için yapılandırılabilir, OpenAI-uyumlu lokal LLM uç noktası.
# Sabit bir cloud API anahtarı GÖMÜLMEZ. İşyerinde Ollama/LM Studio/vLLM gibi
# bir lokal sunucuya bu ortam değişkenleriyle yönlendirilir.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "local")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "180"))

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
SKILLS_DIR.mkdir(parents=True, exist_ok=True)
