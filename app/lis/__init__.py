"""Adaptadores de integração com o LIS.

Cada LIS tem sua forma de receber o cadastro (API REST, banco, arquivo,
HL7/ASTM...). Implemente `AdaptadorLIS` para o seu e selecione via
CHECKEXAME_LIS_ADAPTER.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from .. import config
from ..models import Requisicao


class ErroLIS(Exception):
    pass


def validar_para_os(req: Requisicao) -> list[str]:
    """Pendências que impedem a criação da O.S."""
    erros = []
    if not req.paciente.nome.strip():
        erros.append("Nome do paciente é obrigatório.")
    if not req.paciente.data_nascimento.strip():
        erros.append("Data de nascimento é obrigatória.")
    if not req.exames:
        erros.append("Nenhum exame na requisição.")
    for i, ex in enumerate(req.exames, 1):
        if not ex.codigo_lis:
            erros.append(f"Exame {i} ('{ex.texto_original}') sem código do LIS.")
    return erros


def codigo_pedido(leitura_id: int, criado_em: str) -> str:
    """Código único e estável do pedido: prefixo + data da leitura + id."""
    data = (criado_em or "")[:10].replace("-", "")[2:] or datetime.now().strftime("%y%m%d")
    return f"{config.SHIFT_PREFIXO}{data}{leitura_id:05d}"


def montar_payload(req: Requisicao, leitura_id: int, criado_em: str = "", materiais: dict | None = None) -> dict:
    """Formato neutro de O.S. — o adaptador converte para o formato do LIS."""
    materiais = materiais or {}
    return {
        "origem": "checkexame",
        "leitura_id": leitura_id,
        "codigo_pedido": codigo_pedido(leitura_id, criado_em),
        "paciente": req.paciente.model_dump(),
        "convenio": req.convenio.model_dump(),
        "medico": req.medico.model_dump(),
        "data_solicitacao": req.data_solicitacao,
        "cid": req.cid,
        "indicacao_clinica": req.indicacao_clinica,
        "urgente": req.urgente,
        "observacoes": req.observacoes,
        "exames": [
            {"codigo": e.codigo_lis, "nome": e.nome_lis, "material": materiais.get(e.codigo_lis, ""),
             "texto_requisicao": e.texto_original, "observacao": e.observacao}
            for e in req.exames
        ],
    }


class AdaptadorLIS(ABC):
    nome = ""

    def pendencias(self, payload: dict) -> list[str]:
        """Validações específicas do LIS (além de validar_para_os)."""
        return []

    @abstractmethod
    def criar_os(self, payload: dict) -> dict:
        """Cria a O.S. e devolve ao menos {"os_numero": "..."}."""


class AdaptadorShift(AdaptadorLIS):
    """LIS Shift via web service de recepção de pedidos (ver app/lis/shift.py)."""

    nome = "shift"

    def pendencias(self, payload: dict) -> list[str]:
        from .shift import pendencias_shift

        return pendencias_shift(payload)

    def criar_os(self, payload: dict) -> dict:
        from .shift import ErroShift, enviar

        try:
            return enviar(payload)
        except ErroShift as e:
            raise ErroLIS(str(e)) from e


class AdaptadorMock(AdaptadorLIS):
    """Simula o LIS gravando o payload em data/os_geradas/<numero>.json."""

    nome = "mock"

    def criar_os(self, payload: dict) -> dict:
        numero = datetime.now().strftime("%y%m%d%H%M%S") + f"{payload['leitura_id']:04d}"
        destino = config.OS_DIR / f"{numero}.json"
        destino.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"os_numero": numero, "arquivo": str(destino)}


class AdaptadorHTTP(AdaptadorLIS):
    """POST do payload em CHECKEXAME_LIS_URL. Espera JSON com 'os_numero' (ou 'numero'/'id')."""

    nome = "http"

    def criar_os(self, payload: dict) -> dict:
        if not config.LIS_URL:
            raise ErroLIS("CHECKEXAME_LIS_URL não configurada.")
        headers = {"Authorization": f"Bearer {config.LIS_TOKEN}"} if config.LIS_TOKEN else {}
        try:
            r = httpx.post(config.LIS_URL, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ErroLIS(f"Falha ao enviar para o LIS: {e}") from e
        dados = r.json()
        numero = dados.get("os_numero") or dados.get("numero") or dados.get("id")
        if not numero:
            raise ErroLIS(f"Resposta do LIS sem número da O.S.: {dados}")
        return {"os_numero": str(numero), "resposta": dados}


def obter_adaptador() -> AdaptadorLIS:
    adaptadores = {a.nome: a for a in (AdaptadorMock(), AdaptadorHTTP(), AdaptadorShift())}
    if config.LIS_ADAPTER not in adaptadores:
        raise ErroLIS(f"Adaptador LIS desconhecido: {config.LIS_ADAPTER}")
    return adaptadores[config.LIS_ADAPTER]
