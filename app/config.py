import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CHECKEXAME_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OS_DIR = DATA_DIR / "os_geradas"
DB_PATH = DATA_DIR / "checkexame.db"
# Bases reais do laboratório (exportadas do LIS). Ficam fora do Git (.gitignore).
# Sem elas, o sistema usa os exemplos em data/.
LAB_DIR = Path(os.getenv("CHECKEXAME_BASES", BASE_DIR / "dados_lab"))


def _base(nome: str, exemplo: str) -> Path:
    for ext in (".xlsx", ".csv", ".txt"):
        if (LAB_DIR / f"{nome}{ext}").exists():
            return LAB_DIR / f"{nome}{ext}"
    return BASE_DIR / "data" / exemplo


CATALOGO_PATH = Path(os.getenv("CHECKEXAME_CATALOGO") or _base("exames", "catalogo_exames.csv"))
MEDICOS_PATH = Path(os.getenv("CHECKEXAME_MEDICOS") or _base("medicos", "medicos.csv"))

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

# Acesso: se CHECKEXAME_SENHA estiver definida, o site pede usuário e senha (HTTP Basic)
USUARIO = os.getenv("CHECKEXAME_USUARIO", "checkexame")
SENHA = os.getenv("CHECKEXAME_SENHA", "")

# Integração Shift (web service de recepção de pedidos)
#   SHIFT_URL vazio = modo arquivo: o XML é gerado em data/os_geradas/ sem envio
SHIFT_URL = os.getenv("CHECKEXAME_SHIFT_URL", "")
#   "integracao": ImportaPedidoSinc(IdIntegracao, Usuario, Senha, Pedidos) — formato do XML de exemplo
#   "hospital":   RecebePedido(idHospital, pedidoLab) — formato do documento v1.3
SHIFT_MODELO = os.getenv("CHECKEXAME_SHIFT_MODELO", "integracao")
SHIFT_ID_INTEGRACAO = os.getenv("CHECKEXAME_SHIFT_ID_INTEGRACAO", "")  # IdIntegracao / idHospital
SHIFT_USUARIO = os.getenv("CHECKEXAME_SHIFT_USUARIO", "")
SHIFT_SENHA = os.getenv("CHECKEXAME_SHIFT_SENHA", "")
SHIFT_NAMESPACE = os.getenv("CHECKEXAME_SHIFT_NAMESPACE", "http://tempuri.org")
SHIFT_SOAP_ACTION = os.getenv("CHECKEXAME_SHIFT_SOAP_ACTION", "")
SHIFT_METODO = os.getenv("CHECKEXAME_SHIFT_METODO", "")  # vazio = ImportaPedidoSinc ou RecebePedido conforme o modelo
SHIFT_POSTO = os.getenv("CHECKEXAME_SHIFT_POSTO", "")  # código do posto/setor de coleta
SHIFT_CONVENIO_PADRAO = os.getenv("CHECKEXAME_SHIFT_CONVENIO_PADRAO", "")  # usado quando o convênio não é reconhecido
SHIFT_PREFIXO = os.getenv("CHECKEXAME_SHIFT_PREFIXO", "CKX")  # prefixo do código do pedido gerado
SHIFT_TIMEOUT = float(os.getenv("CHECKEXAME_SHIFT_TIMEOUT", "60"))
CONVENIOS_PATH = Path(os.getenv("CHECKEXAME_CONVENIOS") or _base("fontes_pagadoras", "convenios.csv"))
