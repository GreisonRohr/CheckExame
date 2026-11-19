"""Modelos de dados da requisição médica.

O mesmo formato é usado por todos os extratores (Claude, texto) e é o que a
tela de revisão edita e o adaptador do LIS recebe.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Paciente(BaseModel):
    nome: str = ""
    data_nascimento: str = ""  # DD/MM/AAAA
    sexo: str = ""  # M, F ou vazio
    cpf: str = ""
    cns: str = ""  # Cartão Nacional de Saúde
    telefone: str = ""
    nome_mae: str = ""


class Convenio(BaseModel):
    nome: str = ""  # vazio ou "PARTICULAR" quando não houver
    plano: str = ""
    carteirinha: str = ""
    validade_carteirinha: str = ""
    numero_guia: str = ""


class Medico(BaseModel):
    nome: str = ""
    conselho: str = ""  # CRM, CRO, COREN...
    numero_conselho: str = ""
    uf_conselho: str = ""


class SugestaoExame(BaseModel):
    codigo: str
    nome: str
    score: float


class Exame(BaseModel):
    texto_original: str  # como está escrito na requisição
    nome_interpretado: str = ""  # nome por extenso que o extrator entendeu
    observacao: str = ""
    # Preenchidos pelo mapeamento com o catálogo do LIS
    codigo_lis: str = ""
    nome_lis: str = ""
    status_mapeamento: Literal["ok", "revisar", "nao_encontrado", "manual"] = "nao_encontrado"
    score: float = 0.0
    sugestoes: list[SugestaoExame] = Field(default_factory=list)


class Requisicao(BaseModel):
    paciente: Paciente = Field(default_factory=Paciente)
    convenio: Convenio = Field(default_factory=Convenio)
    medico: Medico = Field(default_factory=Medico)
    data_solicitacao: str = ""
    cid: str = ""
    indicacao_clinica: str = ""
    urgente: bool = False
    exames: list[Exame] = Field(default_factory=list)
    observacoes: str = ""
    legibilidade: Literal["boa", "media", "ruim", ""] = ""
    campos_incertos: list[str] = Field(default_factory=list)
    alertas: list[str] = Field(default_factory=list)
