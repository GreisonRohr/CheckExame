from openpyxl import Workbook

from app.catalogo import Catalogo
from app.convenios import Convenios
from app.medicos import Medicos
from app.models import Medico
from app.tabelas import ler_tabela

med = Medicos.carregar()


def test_medico_por_crm_uf():
    m = med.comparar(Medico(nome="Dr. Joao P. Lima", conselho="CRM", numero_conselho="123.456", uf_conselho="SP"))
    assert m.situacao == "ok" and m.codigo == "M001" and m.nome == "João Pereira Lima"
    assert "123.456" in m.lido


def test_medico_numero_sem_uf_desempata_pelo_nome():
    # 23456 existe em RS e SC; o nome decide
    m = med.comparar(Medico(nome="Carlos E. Souza", numero_conselho="23456"))
    assert m.situacao == "ok" and m.codigo == "M003"
    m = med.comparar(Medico(nome="", numero_conselho="23456"))
    assert m.situacao == "revisar" and {s["codigo"] for s in m.sugestoes} == {"M003", "M004"}


def test_medico_so_nome_vira_revisar():
    m = med.comparar(Medico(nome="Dra Mariana Rocha"))
    assert m.situacao == "revisar" and m.sugestoes[0]["codigo"] == "M005"
    assert med.comparar(Medico(nome="Fulano Inexistente", numero_conselho="999999")).situacao == "nao_encontrado"


def test_outros_conselhos():
    m = med.comparar(Medico(nome="Ricardo Nunes", conselho="CRO", numero_conselho="11223", uf_conselho="RS"))
    assert m.situacao == "ok" and m.conselho == "CRO"


def test_busca():
    assert med.buscar("5432")[0]["codigo"] == "M002"
    assert med.buscar("fernanda")[0]["codigo"] == "M007"


def test_bases_em_excel_e_latin1(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Mnemônico", "Descrição", "Material", "Ativo"])
    ws.append(["HEMO", "HEMOGRAMA COMPLETO", "Sangue Total", "S"])
    ws.append(["VELHO", "EXAME DESATIVADO", "SORO", "N"])
    ws.append(["GLIC", "DOSAGEM DE GLICOSE", "SORO", "S"])
    wb.save(tmp_path / "exames.xlsx")
    cat = Catalogo.carregar(tmp_path / "exames.xlsx")
    assert set(cat.itens) == {"HEMO", "GLIC"}
    assert cat.buscar_exato("dosagem de glicose") == "GLIC"

    (tmp_path / "fontes.csv").write_bytes("Código,Razão Social\nUNI,UNIMED PORTO ALEGRE\nIPE,IPÊ SAÚDE\n".encode("cp1252"))
    conv = Convenios.carregar(tmp_path / "fontes.csv")
    assert conv.mapear("Ipê Saúde") == "IPE"
    assert conv.mapear("Unimed POA", {"unimed poa": "UNI"}) == "UNI"

    (tmp_path / "medicos.csv").write_text("Nome;CRM;Conselho\nPaula Dias;12345/RS;CRM\n", encoding="utf-8")
    m = Medicos.carregar(tmp_path / "medicos.csv")
    assert m.itens[0].uf == "RS" and m.itens[0].numero == "12345"
    assert ler_tabela(tmp_path / "medicos.csv")[0]["crm"] == "12345/RS"


def test_api_medico_e_aprendizado_convenio():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    texto = "Paciente: Ana\nConvênio: Plano Saúde Gaúcho\nExames: hemograma\nDra. Ana Beatriz Costa\nCRM-RS 54321"
    leitura = c.post("/api/leituras", data={"extrator": "texto", "texto": texto}).json()
    d = leitura["dados"]
    assert d["medico"]["situacao"] == "ok" and d["medico"]["codigo"] == "M002"
    assert d["convenio"]["codigo"] == ""  # convênio desconhecido
    d["convenio"]["codigo"] = "CASSI"  # recepcionista seleciona
    c.put(f"/api/leituras/{leitura['id']}", json=d)
    nova = c.post("/api/leituras", data={"extrator": "texto", "texto": texto}).json()
    assert nova["dados"]["convenio"]["codigo"] == "CASSI"
    assert c.get("/api/bases").json()["medicos"]["registros"] == 7
