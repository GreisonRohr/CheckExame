import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

from app import config
from app.lis import shift

EXEMPLO = (Path(__file__).parent / "dados" / "shift_pedido_exemplo.xml").read_text(encoding="utf-8")

PAYLOAD = {
    "leitura_id": 7,
    "codigo_pedido": "CKX26111900007",
    "paciente": {"codigo": "", "nome": "Maria da Silva", "data_nascimento": "21/07/1984", "sexo": "F",
                 "cpf": "123.456.789-09", "cns": "", "telefone": "(51) 99999-1234", "nome_mae": ""},
    "convenio": {"codigo": "UNIMED", "nome": "Unimed", "plano": "Pleno", "carteirinha": "0123456789",
                 "validade_carteirinha": "31/12/2027", "numero_guia": ""},
    "medico": {"nome": "João Pereira", "conselho": "CRM", "numero_conselho": "123456", "uf_conselho": "rs"},
    "data_solicitacao": "18/11/2026", "cid": "I10", "indicacao_clinica": "check-up", "urgente": True,
    "observacoes": "",
    "exames": [{"codigo": "HEMO", "nome": "Hemograma completo", "material": "Sangue Total (HEMO)", "observacao": ""},
               {"codigo": "GLIC", "nome": "Glicose", "material": "SORO", "observacao": "jejum 8h"}],
}


def _estrutura(el, prefixo=""):
    """Sequência de caminhos de tags (sem repetição) para comparar com o exemplo."""
    vistos = []
    for filho in el:
        caminho = f"{prefixo}/{filho.tag}"
        if caminho not in vistos:
            vistos.append(caminho)
        vistos += [c for c in _estrutura(filho, caminho) if c not in vistos]
    return vistos


def test_xml_segue_estrutura_do_exemplo():
    exemplo = ET.fromstring(re.search(r"<!\[CDATA\[(.*)\]\]>", EXEMPLO, re.S).group(1))
    gerado = ET.fromstring(shift.gerar_pedido_xml(PAYLOAD))
    esperado = _estrutura(exemplo)
    obtido = _estrutura(gerado)
    # tudo o que o exemplo tem, o gerado tem, na mesma ordem relativa
    assert [c for c in obtido if c in esperado] == esperado
    # extras previstos no documento v1.3
    assert {"/pedido/posto", "/pedido/convenio", "/pedido/dadosCadastrais"} <= set(obtido)


def test_conteudo_do_pedido():
    el = ET.fromstring(shift.gerar_pedido_xml(PAYLOAD))
    assert el.findtext("pedido/codigo") == "CKX26111900007"
    assert el.findtext("pedido/convenio") == "UNIMED"
    assert el.findtext("paciente/dtNascimento") == "1984-07-21"
    assert el.findtext("paciente/cpf") == "12345678909"
    assert el.findtext("paciente/codigo") == "12345678909"  # sem código: usa o CPF
    assert el.findtext("paciente/celular") == "51999991234"
    assert el.findtext("paciente/nome") == "MARIA DA SILVA"
    dados = {d.findtext("codigo"): d.findtext("valor") for d in el.iter("dadoCadastral")}
    assert dados == {"PLANO": "Pleno", "CARTEIRA": "0123456789", "DATAVALIDADECARTEIRA": "2027-12-31"}
    exames = el.findall("exames/exame")
    assert [e.findtext("codigo") for e in exames] == ["HEMO", "GLIC"]
    assert exames[0].findtext("descMaterial") == "Sangue Total (HEMO)"
    assert exames[1].findtext("observacao") == "jejum 8h"
    assert exames[0].findtext("medicos/medico/crm") == "123456"
    assert exames[0].findtext("medicos/medico/uf") == "RS"
    assert exames[0].findtext("urgente") == "1"
    assert "CID: I10" in el.findtext("pedido/observacao")


def test_envelope_modelo_integracao(monkeypatch):
    monkeypatch.setattr(config, "SHIFT_MODELO", "integracao")
    monkeypatch.setattr(config, "SHIFT_ID_INTEGRACAO", "18")
    monkeypatch.setattr(config, "SHIFT_USUARIO", "teste")
    env, acao = shift.gerar_envelope(shift.gerar_pedido_xml(PAYLOAD))
    corpo = ET.fromstring(env.split("\n", 1)[1])[1][0]
    assert corpo.tag.endswith("ImportaPedidoSinc")
    filhos = {c.tag.split("}")[1]: c.text for c in corpo}
    assert filhos["IdIntegracao"] == "18" and filhos["Usuario"] == "teste"
    assert ET.fromstring(filhos["Pedidos"]).tag == "pedidoLab"
    assert acao.endswith("/ImportaPedidoSinc")


def test_envelope_modelo_hospital(monkeypatch):
    monkeypatch.setattr(config, "SHIFT_MODELO", "hospital")
    monkeypatch.setattr(config, "SHIFT_ID_INTEGRACAO", "H1")
    env, _ = shift.gerar_envelope(shift.gerar_pedido_xml(PAYLOAD))
    corpo = ET.fromstring(env.split("\n", 1)[1])[1][0]
    assert corpo.tag.endswith("RecebePedido")
    assert [c.tag.split("}")[1] for c in corpo] == ["idHospital", "pedidoLab"]


RETORNO_OK = """<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ImportaPedidoSincResponse><ImportaPedidoSincResult>&lt;retornoLab&gt;&lt;pedido&gt;556677&lt;/pedido&gt;
&lt;ordemServico&gt;0119675&lt;/ordemServico&gt;&lt;exames&gt;&lt;exame&gt;&lt;codigo&gt;HEMO&lt;/codigo&gt;
&lt;amostras&gt;&lt;amostra&gt;&lt;codigoBarra&gt;7890001&lt;/codigoBarra&gt;&lt;etiqueta&gt;EDTA&lt;/etiqueta&gt;
&lt;/amostra&gt;&lt;/amostras&gt;&lt;/exame&gt;&lt;/exames&gt;&lt;retorno&gt;true&lt;/retorno&gt;&lt;descErro/&gt;
&lt;/retornoLab&gt;</ImportaPedidoSincResult></ImportaPedidoSincResponse></soap:Body></soap:Envelope>"""


def test_interpretar_retorno_escapado():
    r = shift.interpretar_resposta(RETORNO_OK)
    assert r["ok"] and r["ordem_servico"] == "0119675" and r["pedido"] == "556677"
    assert r["exames"][0]["amostras"][0]["codigo_barra"] == "7890001"


def test_interpretar_erro_e_fault():
    erro = "<x><retornoLab><pedido/><ordemServico/><retorno>false</retorno><descErro>Convênio inexistente</descErro></retornoLab></x>"
    assert shift.interpretar_resposta(erro) == {"ok": False, "pedido": "", "ordem_servico": "",
                                                "erro": "Convênio inexistente", "exames": []}
    fault = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault>'
             "<faultcode>s:Client</faultcode><faultstring>Usuário inválido</faultstring></s:Fault></s:Body></s:Envelope>")
    assert shift.interpretar_resposta(fault)["erro"] == "Usuário inválido"


def test_envio_soap(monkeypatch):
    monkeypatch.setattr(config, "SHIFT_URL", "https://shift.exemplo/csp/ws/Pedido.cls")
    monkeypatch.setattr(config, "SHIFT_POSTO", "01")
    monkeypatch.setattr(config, "SHIFT_ID_INTEGRACAO", "18")
    capturado = {}

    def handler(req: httpx.Request):
        capturado["acao"] = req.headers["SOAPAction"]
        capturado["corpo"] = req.content.decode()
        return httpx.Response(200, text=RETORNO_OK)

    r = shift.enviar(PAYLOAD, cliente=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r["os_numero"] == "0119675"
    assert "<![CDATA[<pedidoLab>" in capturado["corpo"]
    assert capturado["acao"].startswith('"')

    recusa = "<x><retornoLab><retorno>0</retorno><descErro>Posto inválido</descErro></retornoLab></x>"
    with pytest.raises(shift.ErroShift, match="Posto inválido"):
        shift.enviar(PAYLOAD, cliente=httpx.Client(transport=httpx.MockTransport(lambda q: httpx.Response(200, text=recusa))))


def test_pendencias(monkeypatch):
    monkeypatch.setattr(config, "SHIFT_URL", "")
    monkeypatch.setattr(config, "SHIFT_CONVENIO_PADRAO", "")
    p = dict(PAYLOAD, paciente=dict(PAYLOAD["paciente"], sexo="", data_nascimento="31/02/1990"),
             convenio=dict(PAYLOAD["convenio"], codigo=""))
    msgs = " ".join(shift.pendencias_shift(p))
    assert "Sexo" in msgs and "inválida" in msgs and "Convênio" in msgs


def test_fluxo_api_modo_arquivo(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(config, "LIS_ADAPTER", "shift")
    monkeypatch.setattr(config, "SHIFT_URL", "")
    c = TestClient(app)
    texto = "Paciente: Ana Souza\nNascimento: 02/03/1990\nSexo: F\nConvênio: Unimed\nExames: hemograma, glicose, HBsAg"
    leitura = c.post("/api/leituras", data={"extrator": "texto", "texto": texto}).json()
    assert leitura["dados"]["convenio"]["codigo"] == "UNIMED"
    xml = c.get(f"/api/leituras/{leitura['id']}/xml-shift").text
    assert "<codigo>AGHBS</codigo>" in xml and "Pendência" not in xml
    r = c.post(f"/api/leituras/{leitura['id']}/os")
    assert r.status_code == 200, r.text
    assert r.json()["resultado"]["simulado"] is True
    assert Path(r.json()["resultado"]["arquivo"]).exists()


def test_xml_conferencia_e_xml_valido(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    leitura = c.post("/api/leituras", data={"extrator": "texto", "texto": "Paciente: X\nExames: hemograma"}).json()
    xml = c.get(f"/api/leituras/{leitura['id']}/xml-shift").text
    assert xml.startswith("<?xml")
    assert "Pendência" in xml  # sem sexo / nascimento
    ET.fromstring(xml.split("\n", 1)[1])
