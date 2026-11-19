from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Requisicao


class ErroExtracao(Exception):
    """Falha de leitura que deve ser mostrada ao usuário."""


class Extrator(ABC):
    nome: str = ""
    descricao: str = ""

    @abstractmethod
    def disponivel(self) -> tuple[bool, str]:
        """(disponível?, motivo quando não está)."""

    @abstractmethod
    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Requisicao:
        ...
