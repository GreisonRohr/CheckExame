"""Integração com o LIS Shift — web service de recepção de pedidos.

Baseado em "Integra_RecebePedido_WSHIS v1.3" e no XML de exemplo
ImportaPedidoSincRequest. O pedido vai como XML `pedidoLab` (dentro de CDATA)
e o Shift responde com `retornoLab` (O.S., códigos de barras e etiquetas).

Dois modelos de chamada (CHECKEXAME_SHIFT_MODELO):
- "integracao": ImportaPedidoSinc(IdIntegracao, Usuario, Senha, Pedidos)  [XML de exemplo]
- "hospital":   RecebePedido(idHospital, pedidoLab)                       [documento v1.3]

Sem CHECKEXAME_SHIFT_URL o adaptador trabalha em modo arquivo: gera o XML em
data/os_geradas/ para conferência ou importação manual, sem enviar nada.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from .. import config

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

# Limites de tamanho do documento v1.3
LIM = {"nome_paciente": 100, "obs_pedido": 5000, "obs_exame": 2000, "descricao": 100, "material": 200,
       "medico_nome": 50, "padrao": 50}


class ErroShift(Exception):
    pass


# ---------------------------------------------------------------- conversões
def data_iso(valor: str) -> str:
    """DD/MM/AAAA (ou DD/MM/AA) -> AAAA-MM-DD; '' se inválida."""
    valor = (valor or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(valor, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _so_digitos(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def _corta(v, n: int) -> str:
    return str(v or "").strip()[:n]


def codigo_paciente(payload: dict) -> str:
    pac = payload["paciente"]
    if pac.get("codigo"):
        return _corta(pac["codigo"], 50)
    cpf = _so_digitos(pac.get("cpf", ""))
    if len(cpf) == 11:
        return cpf
    return f"{config.SHIFT_PREFIXO}P{payload['leitura_id']}"


def codigo_convenio(payload: dict) -> str:
    return payload["convenio"].get("codigo") or config.SHIFT_CONVENIO_PADRAO


def pendencias_shift(payload: dict) -> list[str]:
    """Regras do documento v1.3 além das validações gerais."""
    p = []
    pac = payload["paciente"]
    if pac.get("sexo") not in ("M", "F"):
        p.append("Sexo do paciente (M ou F) é obrigatório no Shift.")
    if pac.get("data_nascimento") and not data_iso(pac["data_nascimento"]):
        p.append(f"Data de nascimento inválida: '{pac['data_nascimento']}' (use DD/MM/AAAA).")
    if not codigo_convenio(payload):
        p.append(f"Convênio '{payload['convenio'].get('nome', '')}' sem código do Shift "
                 "(informe o código ou configure CHECKEXAME_SHIFT_CONVENIO_PADRAO).")
    if config.SHIFT_URL:
        if not config.SHIFT_POSTO:
            p.append("Configure CHECKEXAME_SHIFT_POSTO (código do posto/setor no Shift).")
        if not config.SHIFT_ID_INTEGRACAO:
            p.append("Configure CHECKEXAME_SHIFT_ID_INTEGRACAO (IdIntegracao/idHospital fornecido pela Shift).")
    return p


# ---------------------------------------------------------------- XML do pedido
def _sub(pai, tag, texto=""):
    el = ET.SubElement(pai, tag)
    el.text = str(texto) if texto not in (None, "") else None
    return el


def gerar_pedido_xml(payload: dict) -> str:
    """XML pedidoLab conforme o documento v1.3 / XML de exemplo."""
    raiz = ET.Element("pedidoLab")

    ped = ET.SubElement(raiz, "pedido")
    _sub(ped, "codigo", _corta(payload["codigo_pedido"], 50))
    _sub(ped, "ordemServico", _corta(payload["codigo_pedido"], 50))
    _sub(ped, "posto", _corta(config.SHIFT_POSTO, 50))
    _sub(ped, "convenio", _corta(codigo_convenio(payload), 50))
    obs = []
    if payload.get("observacoes"):
        obs.append(payload["observacoes"])
    if payload.get("indicacao_clinica"):
        obs.append(f"Indicação clínica: {payload['indicacao_clinica']}")
    if payload.get("cid"):
        obs.append(f"CID: {payload['cid']}")
    if payload.get("data_solicitacao"):
        obs.append(f"Data da requisição: {payload['data_solicitacao']}")
    _sub(ped, "observacao", _corta(" | ".join(obs), LIM["obs_pedido"]))
    conv = payload["convenio"]
    dados = [("PLANO", conv.get("plano")), ("CARTEIRA", conv.get("carteirinha")),
             ("DATAVALIDADECARTEIRA", data_iso(conv.get("validade_carteirinha", ""))),
             ("GUIA", conv.get("numero_guia"))]
    dados = [(c, v) for c, v in dados if v]
    if dados:
        dc = ET.SubElement(ped, "dadosCadastrais")
        for cod, valor in dados:
            d = ET.SubElement(dc, "dadoCadastral")
            _sub(d, "codigo", cod)
            _sub(d, "valor", _corta(valor, 1000))

    pac_in = payload["paciente"]
    pac = ET.SubElement(raiz, "paciente")
    _sub(pac, "codigo", codigo_paciente(payload))
    _sub(pac, "nome", _corta(pac_in.get("nome", "").upper(), LIM["nome_paciente"]))
    _sub(pac, "sexo", pac_in.get("sexo", ""))
    _sub(pac, "dtNascimento", data_iso(pac_in.get("data_nascimento", "")))
    for tag in ("altura", "peso", "dum", "rg"):
        _sub(pac, tag)
    _sub(pac, "cpf", _so_digitos(pac_in.get("cpf", "")))
    _sub(pac, "cns", _so_digitos(pac_in.get("cns", "")))
    _sub(pac, "email")
    tel = _so_digitos(pac_in.get("telefone", ""))
    celular = len(tel) in (11, 13) or (len(tel) >= 9 and tel[-9] == "9")
    _sub(pac, "telefone", "" if celular else tel)
    _sub(pac, "celular", tel if celular else "")
    _sub(pac, "medicamento")
    _sub(pac, "anamnese")

    med_in = payload["medico"]
    exs = ET.SubElement(raiz, "exames")
    for e in payload["exames"]:
        ex = ET.SubElement(exs, "exame")
        _sub(ex, "codigo", _corta(e["codigo"], 50))
        _sub(ex, "descricao", _corta(e.get("nome", "").upper(), LIM["descricao"]))
        amostra = ET.SubElement(ET.SubElement(ex, "amostras"), "amostra")
        _sub(amostra, "codigoBarra")
        _sub(amostra, "recipiente")
        _sub(ex, "descMaterial", _corta(e.get("material", ""), LIM["material"]))
        _sub(ex, "observacao", _corta(e.get("observacao", ""), LIM["obs_exame"]))
        med = ET.SubElement(ET.SubElement(ex, "medicos"), "medico")
        _sub(med, "nome", _corta(med_in.get("nome", "").upper(), LIM["medico_nome"]))
        _sub(med, "crm", _so_digitos(med_in.get("numero_conselho", "")))
        _sub(med, "conselho", _corta(med_in.get("conselho", "").upper(), 50))
        _sub(med, "uf", _corta(med_in.get("uf_conselho", "").upper(), 2))
        _sub(ex, "urgente", "1" if payload.get("urgente") else "0")

    ET.indent(raiz, space="\t")
    return ET.tostring(raiz, encoding="unicode")


def _cdata(texto: str) -> str:
    return "<![CDATA[" + texto.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def gerar_envelope(pedido_xml: str) -> tuple[str, str]:
    """(envelope SOAP, SOAPAction)."""
    ns = config.SHIFT_NAMESPACE
    esc = lambda v: html.escape(str(v or ""), quote=False)  # noqa: E731
    if config.SHIFT_MODELO == "hospital":
        metodo = config.SHIFT_METODO or "RecebePedido"
        params = (f"<tns:idHospital>{esc(config.SHIFT_ID_INTEGRACAO)}</tns:idHospital>"
                  f"<tns:pedidoLab>{_cdata(pedido_xml)}</tns:pedidoLab>")
    else:
        metodo = config.SHIFT_METODO or "ImportaPedidoSinc"
        params = (f"<tns:IdIntegracao>{esc(config.SHIFT_ID_INTEGRACAO)}</tns:IdIntegracao>"
                  f"<tns:Usuario>{esc(config.SHIFT_USUARIO)}</tns:Usuario>"
                  f"<tns:Senha>{esc(config.SHIFT_SENHA)}</tns:Senha>"
                  f"<tns:Pedidos>{_cdata(pedido_xml)}</tns:Pedidos>")
    envelope = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV}" xmlns:tns="{esc(ns)}">'
                f"<soapenv:Header/><soapenv:Body><tns:{metodo}>{params}</tns:{metodo}>"
                f"</soapenv:Body></soapenv:Envelope>")
    acao = config.SHIFT_SOAP_ACTION or f"{ns.rstrip('/')}/{metodo}"
    return envelope, acao


# ---------------------------------------------------------------- resposta
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _texto(el, nome: str) -> str:
    for filho in el.iter():
        if _local(filho.tag) == nome.lower() and filho is not el:
            return (filho.text or "").strip()
    return ""


def _verdadeiro(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "s", "sim", "t", "y", "yes")


def interpretar_resposta(corpo: str) -> dict:
    """Extrai o retornoLab (que pode vir escapado dentro de um campo string)."""
    texto = corpo
    for _ in range(3):
        if re.search(r"<retorno[Ll]ab\b", texto):
            break
        texto = html.unescape(texto)
    m = re.search(r"<retorno[Ll]ab\b.*?</retorno[Ll]ab>", texto, re.S)
    if m:
        try:
            el = ET.fromstring(m.group(0))
        except ET.ParseError as e:
            raise ErroShift(f"retornoLab inválido: {e}") from e
        exames = []
        for ex in el.iter():
            if _local(ex.tag) == "exame":
                amostras = [{"codigo_barra": _texto(a, "codigoBarra"), "etiqueta": _texto(a, "etiqueta")}
                            for a in ex.iter() if _local(a.tag) == "amostra"]
                exames.append({"codigo": _texto(ex, "codigo"), "amostras": amostras})
        return {
            "ok": _verdadeiro(_texto(el, "retorno")),
            "pedido": _texto(el, "pedido"),
            "ordem_servico": _texto(el, "ordemServico"),
            "erro": _texto(el, "descErro"),
            "exames": exames,
        }
    # Sem retornoLab: tenta os parâmetros de saída do documento (pRetornoCliente / pDescricaoErro) ou SOAP Fault
    try:
        el = ET.fromstring(corpo)
    except ET.ParseError as e:
        raise ErroShift(f"Resposta do Shift não é XML: {corpo[:300]}") from e
    falha = _texto(el, "faultstring")
    if falha:
        return {"ok": False, "pedido": "", "ordem_servico": "", "erro": falha, "exames": []}
    ret = _texto(el, "pRetornoCliente")
    if ret:
        return {"ok": _verdadeiro(ret), "pedido": "", "ordem_servico": "", "erro": _texto(el, "pDescricaoErro"), "exames": []}
    raise ErroShift(f"Resposta do Shift sem retornoLab: {corpo[:300]}")


# ---------------------------------------------------------------- envio
def enviar(payload: dict, cliente: httpx.Client | None = None) -> dict:
    pedido_xml = gerar_pedido_xml(payload)
    envelope, acao = gerar_envelope(pedido_xml)
    codigo = payload["codigo_pedido"]

    if not config.SHIFT_URL:  # modo arquivo
        destino = config.OS_DIR / f"{codigo}.xml"
        destino.write_text(envelope, encoding="utf-8")
        return {"os_numero": codigo, "simulado": True, "arquivo": str(destino),
                "mensagem": "Modo arquivo: XML gerado, nada foi enviado ao Shift."}

    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{acao}"'}
    try:
        if cliente is None:
            with httpx.Client(timeout=config.SHIFT_TIMEOUT) as c:
                r = c.post(config.SHIFT_URL, content=envelope.encode("utf-8"), headers=headers)
        else:
            r = cliente.post(config.SHIFT_URL, content=envelope.encode("utf-8"), headers=headers)
    except httpx.HTTPError as e:
        raise ErroShift(f"Falha de conexão com o Shift: {e}") from e
    if r.status_code >= 400 and "fault" not in r.text.lower():
        raise ErroShift(f"Shift respondeu HTTP {r.status_code}: {r.text[:300]}")

    ret = interpretar_resposta(r.text)
    if not ret["ok"]:
        raise ErroShift(f"Shift recusou o pedido: {ret['erro'] or 'sem descrição do erro'}")
    return {"os_numero": ret["ordem_servico"] or ret["pedido"] or codigo, "pedido_shift": ret["pedido"],
            "exames": ret["exames"], "codigo_pedido": codigo}
