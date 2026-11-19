"""Tabela de convênios do LIS e mapeamento nome lido -> código."""
from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz, process

from . import config
from .catalogo import normalizar


class Convenios:
    def __init__(self, itens: list[tuple[str, str, list[str]]]):
        self.nomes = {codigo: nome for codigo, nome, _ in itens}
        self._termos: dict[str, str] = {}
        for codigo, nome, sinonimos in itens:
            for t in (codigo, nome, *sinonimos):
                if normalizar(t):
                    self._termos.setdefault(normalizar(t), codigo)

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Convenios":
        caminho = caminho or config.CONVENIOS_PATH
        if not Path(caminho).exists():
            return cls([])
        from .tabelas import campo, inativo, ler_tabela

        itens = []
        for r in ler_tabela(caminho):
            codigo = campo(r, "codigo", "cod_convenio", "codigo_convenio", "convenio", "fonte_pagadora", "sigla")
            nome = campo(r, "nome", "descricao", "razao_social", "nome_convenio", "fantasia")
            if not codigo or inativo(r):
                continue
            sin = [s.strip() for s in re.split(r"[|;,]", campo(r, "sinonimos", "apelidos")) if s.strip()]
            itens.append((codigo, nome or codigo, sin))
        return cls(itens)

    def listar(self) -> list[dict]:
        return [{"codigo": c, "nome": n} for c, n in sorted(self.nomes.items(), key=lambda x: x[1])]

    def mapear(self, nome: str, aprendidos: dict[str, str] | None = None) -> str:
        """Código do convênio para o nome lido na requisição ('' se não reconhecido)."""
        n = normalizar(nome)
        if not n:
            return ""
        if aprendidos and aprendidos.get(n) in self.nomes:
            return aprendidos[n]
        if n in self._termos:
            return self._termos[n]
        termos = [t for t in self._termos if len(t) >= 3]
        achado = process.extractOne(n, termos, scorer=fuzz.WRatio, score_cutoff=88)
        return self._termos[achado[0]] if achado else ""
