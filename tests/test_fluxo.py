import os
import tempfile
from pathlib import Path

os.environ.setdefault("CHECKEXAME_DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from app.catalogo import Catalogo, normalizar  # noqa: E402
from app.extractors.texto import ExtratorTexto  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Exame  # noqa: E402

EXEMPLO = Path(__file__).parent.parent / "exemplos" / "requisicao_impressa.txt"
cat = Catalogo.carregar()
client = TestClient(app)


def test_normalizar():
    assert normalizar("  Ácido Úrico. ") == "acido urico"


def test_mapeamento_exato_e_sigla():
    for texto, codigo in [("Hemograma completo", "HEMO"), ("TGO", "TGO"), ("Urina tipo 1", "EAS"),
                          ("glicemia de jejum", "GLIC"), ("Vit D", "VITD"), ("K", "K")]:
        ex = cat.mapear(Exame(texto_original=texto))
        assert ex.codigo_lis == codigo, texto
        assert ex.status_mapeamento == "ok"


def test_mapeamento_aproximado():
    ex = cat.mapear(Exame(texto_original="hemogrma complto"))
    assert ex.codigo_lis == "HEMO"
    ex = cat.mapear(Exame(texto_original="xyzabc qwerty"))
    assert ex.status_mapeamento == "nao_encontrado"


def test_nome_interpretado_ajuda():
    ex = cat.mapear(Exame(texto_original="Ht gl", nome_interpretado="Hemoglobina glicada"))
    assert ex.codigo_lis == "HBA1C"


def test_extrator_texto():
    req = ExtratorTexto(cat).extrair_texto(EXEMPLO.read_text(encoding="utf-8"))
    assert req.paciente.nome == "Maria Aparecida dos Santos"
    assert req.paciente.data_nascimento == "14/03/1975"
    assert req.paciente.cpf == "12345678909"
    assert req.paciente.sexo == "F"
    assert req.convenio.nome == "Unimed"
    assert req.medico.conselho == "CRM" and req.medico.numero_conselho == "123456" and req.medico.uf_conselho == "SP"
    assert req.cid == "I10"
    textos = [e.texto_original for e in req.exames]
    assert "Ureia" in textos and "creatinina" in textos and "TSH" in textos


def test_fluxo_completo_api():
    r = client.post("/api/leituras", data={"extrator": "texto"},
                    files={"arquivo": ("req.txt", EXEMPLO.read_bytes(), "text/plain")})
    assert r.status_code == 200, r.text
    leitura = r.json()
    assert leitura["status"] == "lida"
    dados = leitura["dados"]

    # corrige manualmente os exames não mapeados (e ensina o sinônimo)
    for ex in dados["exames"]:
        if not ex["codigo_lis"]:
            ex["codigo_lis"], ex["status_mapeamento"] = "PLIP", "manual"
    r = client.put(f"/api/leituras/{leitura['id']}", json=dados)
    assert r.status_code == 200 and r.json()["status"] == "revisada"

    r = client.post(f"/api/leituras/{leitura['id']}/os")
    assert r.status_code == 200, r.text
    assert r.json()["os_numero"]
    assert client.post(f"/api/leituras/{leitura['id']}/os").status_code == 409


def test_os_bloqueada_sem_dados_obrigatorios():
    r = client.post("/api/leituras", data={"extrator": "texto", "texto": "Exames: hemograma"})
    leitura = r.json()
    r = client.post(f"/api/leituras/{leitura['id']}/os")
    assert r.status_code == 422
    assert any("paciente" in p for p in r.json()["detail"]["pendencias"])


def test_sinonimo_aprendido():
    r = client.post("/api/leituras", data={"extrator": "texto", "texto": "Paciente: X\nExames: perfil do ferro especial"})
    leitura = r.json()
    dados = leitura["dados"]
    dados["exames"][0].update(codigo_lis="FERRO", status_mapeamento="manual")
    client.put(f"/api/leituras/{leitura['id']}", json=dados)
    r = client.post("/api/leituras", data={"extrator": "texto", "texto": "Exames: perfil do ferro especial"})
    assert r.json()["dados"]["exames"][0]["codigo_lis"] == "FERRO"


def test_claude_indisponivel_sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = client.post("/api/leituras", data={"extrator": "claude", "texto": "Exames: hemograma"})
    assert r.json()["status"] == "erro"


def test_senha(monkeypatch):
    import base64

    from app import config

    monkeypatch.setattr(config, "SENHA", "s3gredo")
    assert client.get("/api/extratores").status_code == 401
    assert client.get("/saude").status_code == 200
    ok = base64.b64encode(b"checkexame:s3gredo").decode()
    assert client.get("/api/extratores", headers={"Authorization": f"Basic {ok}"}).status_code == 200
    ruim = base64.b64encode(b"checkexame:errada").decode()
    assert client.get("/api/extratores", headers={"Authorization": f"Basic {ruim}"}).status_code == 401
