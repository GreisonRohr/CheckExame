import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CHECKEXAME_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OS_DIR = DATA_DIR / "os_geradas"
DB_PATH = DATA_DIR / "checkexame.db"
CATALOGO_PATH = Path(os.getenv("CHECKEXAME_CATALOGO", BASE_DIR / "data" / "catalogo_exames.csv"))

# Claude
CLAUDE_MODEL = os.getenv("CHECKEXAME_CLAUDE_MODEL", "claude-opus-5-5")
# low | medium | high | xhigh | max — manuscritos difíceis se beneficiam de "high"
CLAUDE_EFFORT = os.getenv("CHECKEXAME_CLAUDE_EFFORT", "high")

# Mapeamento de exames
SCORE_OK = float(os.getenv("CHECKEXAME_SCORE_OK", "90"))
SCORE_REVISAR = float(os.getenv("CHECKEXAME_SCORE_REVISAR", "70"))

# LIS: "mock" (grava JSON em data/os_geradas) ou "http" (POST em LIS_URL)
LIS_ADAPTER = os.getenv("CHECKEXAME_LIS_ADAPTER", "mock")
LIS_URL = os.getenv("CHECKEXAME_LIS_URL", "")
LIS_TOKEN = os.getenv("CHECKEXAME_LIS_TOKEN", "")

for d in (DATA_DIR, UPLOAD_DIR, OS_DIR):
    d.mkdir(parents=True, exist_ok=True)
