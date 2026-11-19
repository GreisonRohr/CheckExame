from ..catalogo import Catalogo
from .base import ErroExtracao, Extrator
from .claude_vision import ExtratorClaude
from .texto import ExtratorTexto


def criar_extratores(catalogo: Catalogo) -> dict[str, Extrator]:
    return {e.nome: e for e in (ExtratorClaude(), ExtratorTexto(catalogo))}


__all__ = ["ErroExtracao", "Extrator", "criar_extratores"]
