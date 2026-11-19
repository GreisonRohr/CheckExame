"""Extrator por regras para requisições em texto (TXT ou PDF com camada de texto).

Não usa IA: serve para testar o fluxo sem chave de API e para pedidos
impressos por sistemas (prontuário eletrônico), onde o texto é limpo.
"""
from __future__ import annotations

import io
import re

from ..catalogo import Catalogo, normalizar
from ..models import Exame, Requisicao
from .base import ErroExtracao, Extrator

RE_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
RE_DATA = re.compile(r"\b(\d{2})[/.-](\d{2})[/.-](\d{2,4})\b")
RE_CRM = re.compile(r"\b(CRM|CRO|COREN|CRBM|CRN)\s*[-/:]?\s*([A-Z]{2})?\s*[-/:]?\s*(\d{3,7})\s*[-/]?\s*([A-Z]{2})?", re.I)
RE_CID = re.compile(r"\bCID(?:-?10)?\s*[:\-]?\s*([A-TV-Z]\d{2}(?:\.\d)?)", re.I)

ROTULOS = {
    "paciente.nome": r"(?:paciente|nome do paciente|nome)",
    "paciente.data_nascimento": r"(?:data de nascimento|nascimento|dt\.? nasc\.?|d\.?n\.?)",
    "paciente.nome_mae": r"(?:nome da m[aã]e|m[aã]e)",
    "paciente.telefone": r"(?:telefone|tel\.?|celular|fone)",
    "paciente.cns": r"(?:cns|cart[aã]o sus|cart[aã]o nacional de sa[uú]de)",
    "convenio.nome": r"(?:conv[eê]nio|operadora)",
    "convenio.plano": r"(?:plano)",
    "convenio.carteirinha": r"(?:carteirinha|carteira|matr[ií]cula|n[ºo°]?\.? da carteira)",
    "convenio.numero_guia": r"(?:guia|n[ºo°]?\.? guia)",
    "medico.nome": r"(?:m[eé]dico(?: solicitante)?|solicitante|dr\.?a?)",
    "indicacao_clinica": r"(?:indica[cç][aã]o cl[ií]nica|hip[oó]tese diagn[oó]stica|hd)",
    "data_solicitacao": r"(?:data(?: da solicita[cç][aã]o| do pedido)?)",
}
CABECALHO_EXAMES = re.compile(
    r"^\s*(exames?(?: solicitados?| laboratoriais| a realizar)?|solicito|pe[cç]o)\s*(?::|$|\s)\s*(.*)$", re.I
)
RE_DR = re.compile(r"^\s*(?:dr|dra)\.?\s+([A-Za-zÀ-ú][A-Za-zÀ-ú .]{3,60})$", re.I)
MARCADOR_ITEM = re.compile(r"^\s*(?:[-•*·]|\d{1,2}[).\-]|\(\s*x?\s*\)|\[\s*x?\s*\])\s*")


class ExtratorTexto(Extrator):
    nome = "texto"
    descricao = "Regras sobre texto (TXT / PDF digital) — sem IA"

    def __init__(self, catalogo: Catalogo):
        self.catalogo = catalogo

    def disponivel(self) -> tuple[bool, str]:
        return True, ""

    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Requisicao:
        if mime == "application/pdf":
            texto = _texto_pdf(conteudo)
            if len(texto.strip()) < 20:
                raise ErroExtracao("PDF sem camada de texto (digitalizado). Use o extrator Claude.")
        elif mime.startswith("text/"):
            texto = conteudo.decode("utf-8", "replace")
        else:
            raise ErroExtracao("O extrator de texto só lê TXT e PDF digitais. Para imagens use o Claude.")
        return self.extrair_texto(texto)

    # ------------------------------------------------------------------
    def extrair_texto(self, texto: str) -> Requisicao:
        req = Requisicao()
        linhas = [l.rstrip() for l in texto.splitlines()]

        for campo, rotulo in ROTULOS.items():
            valor = _valor_rotulado(linhas, rotulo)
            if valor:
                _set(req, campo, valor)

        if m := RE_CPF.search(texto):
            req.paciente.cpf = re.sub(r"\D", "", m.group(1))
        if not req.medico.nome:
            for linha in linhas:
                if m := RE_DR.match(linha):
                    req.medico.nome = m.group(1).strip()
                    break
        if m := RE_CRM.search(texto):
            req.medico.conselho = m.group(1).upper()
            req.medico.numero_conselho = m.group(3)
            req.medico.uf_conselho = (m.group(2) or m.group(4) or "").upper()
        if m := RE_CID.search(texto):
            req.cid = m.group(1).upper()
        if re.search(r"\b(urgente|urg[eê]ncia|emerg[eê]ncia)\b", texto, re.I):
            req.urgente = True
        if re.search(r"\bsexo\s*:?\s*(m|masc)", texto, re.I):
            req.paciente.sexo = "M"
        elif re.search(r"\bsexo\s*:?\s*(f|fem)", texto, re.I):
            req.paciente.sexo = "F"
        for campo in ("paciente.data_nascimento", "data_solicitacao"):
            v = _get(req, campo)
            if v and (m := RE_DATA.search(v)):
                ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
                _set(req, campo, f"{m.group(1)}/{m.group(2)}/{ano}")
            elif v:
                _set(req, campo, "")

        req.exames = self._exames(linhas)
        if not req.exames:
            req.alertas.append("Nenhum exame identificado no texto.")
        if not req.paciente.nome:
            req.alertas.append("Nome do paciente não encontrado.")
        req.legibilidade = "boa"
        return req

    def _exames(self, linhas: list[str]) -> list[Exame]:
        """Lê itens após um cabeçalho 'Exames:'; sem cabeçalho, procura linhas que batem com o catálogo."""
        trechos: list[str] = []
        dentro = False
        for linha in linhas:
            if m := CABECALHO_EXAMES.match(linha):
                dentro = True
                if m.group(2).strip():
                    trechos.append(m.group(2))
                continue
            if dentro:
                if not linha.strip():
                    if trechos:
                        dentro = False
                    continue
                if re.match(r"^\s*[A-Za-zÀ-ú ]{3,30}:\s*\S", linha) and not MARCADOR_ITEM.match(linha):
                    dentro = False  # começou outro campo rotulado
                    continue
                trechos.append(linha)

        if not trechos:  # fallback: qualquer linha cujo conteúdo esteja no catálogo
            trechos = [l for l in linhas if l.strip() and self.catalogo.buscar_exato(MARCADOR_ITEM.sub("", l))]

        exames: list[Exame] = []
        for trecho in trechos:
            trecho = MARCADOR_ITEM.sub("", trecho)
            for parte in re.split(r"[,;+\n]", trecho):
                parte = MARCADOR_ITEM.sub("", parte).strip(" .\t")
                if not normalizar(parte) or re.fullmatch(r"\d+", parte):
                    continue
                exames.extend(Exame(texto_original=p) for p in self._dividir(parte))
        return exames

    def _dividir(self, parte: str) -> list[str]:
        """Separa "TGO / TGP" ou "ureia e creatinina" só quando cada pedaço é um exame
        conhecido — assim "Colesterol total e frações" continua um item só."""
        if self.catalogo.buscar_exato(parte):
            return [parte]
        pedacos = [p.strip(" .") for p in re.split(r"\s*/\s*|\s+e\s+", parte) if p.strip(" .")]
        if len(pedacos) > 1 and all(self.catalogo.buscar_exato(p) for p in pedacos):
            return pedacos
        return [parte]


def _texto_pdf(conteudo: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(conteudo))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:  # noqa: BLE001
        raise ErroExtracao(f"Não foi possível ler o PDF: {e}") from e


def _valor_rotulado(linhas: list[str], rotulo: str) -> str:
    padrao = re.compile(rf"(?:^|\s|\|){rotulo}\s*[:\-]\s*(.+)", re.I)
    for linha in linhas:
        if m := padrao.search(linha):
            valor = m.group(1)
            # corta no próximo rótulo da mesma linha ("Nome: X   Nasc: Y")
            valor = re.split(r"\s{2,}|\s\|\s|\t", valor)[0]
            return valor.strip(" .;")
    return ""


def _get(req: Requisicao, caminho: str) -> str:
    obj = req
    for p in caminho.split("."):
        obj = getattr(obj, p)
    return obj  # type: ignore[return-value]


def _set(req: Requisicao, caminho: str, valor: str):
    *pais, campo = caminho.split(".")
    obj = req
    for p in pais:
        obj = getattr(obj, p)
    if not getattr(obj, campo):
        setattr(obj, campo, valor)
