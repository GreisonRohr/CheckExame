"""Catálogo de exames do LIS e mapeamento texto -> código.

Ordem de busca para cada exame lido da requisição:
1. Sinônimos aprendidos (correções feitas pelo usuário na tela de revisão);
2. Correspondência exata com nome/sinônimos do catálogo;
3. Correspondência aproximada (rapidfuzz) com sugestões ordenadas por score.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from . import config
from .models import Exame, SugestaoExame


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9+/]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


@dataclass
class ItemCatalogo:
    codigo: str
    nome: str
    sinonimos: list[str] = field(default_factory=list)
    material: str = ""
    setor: str = ""


class Catalogo:
    def __init__(self, itens: list[ItemCatalogo]):
        self.itens = {i.codigo: i for i in itens}
        # termo normalizado -> código
        self._exatos: dict[str, str] = {}
        for item in itens:
            for termo in [item.nome, item.codigo, *item.sinonimos]:
                n = normalizar(termo)
                if n:
                    self._exatos.setdefault(n, item.codigo)
        # termos com 4+ caracteres entram na busca aproximada; siglas curtas
        # ("k", "ur", "fa") só por correspondência exata para evitar falsos positivos
        self._fuzzy_termos = [t for t in self._exatos if len(t) >= 4]

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Catalogo":
        from .tabelas import campo, inativo, ler_tabela

        caminho = caminho or config.CATALOGO_PATH
        itens: dict[str, ItemCatalogo] = {}
        for row in ler_tabela(caminho):
            codigo = campo(row, "codigo", "mnemonico", "mnemônico", "sigla", "cod_exame", "codigo_exame", "exame")
            nome = campo(row, "nome", "descricao", "descrição", "nome_exame", "descricao_exame")
            if not codigo or inativo(row):
                continue
            sinonimos = re.split(r"[|;,]", campo(row, "sinonimos", "sinônimos", "apelidos", "nomes_alternativos"))
            itens.setdefault(codigo, ItemCatalogo(
                codigo=codigo,
                nome=nome or codigo,
                sinonimos=[s.strip() for s in sinonimos if s.strip()],
                material=campo(row, "material", "desc_material", "descmaterial", "amostra"),
                setor=campo(row, "setor", "bancada", "grupo"),
            ))
        return cls(list(itens.values()))

    def listar(self) -> list[dict]:
        return [
            {"codigo": i.codigo, "nome": i.nome, "material": i.material, "setor": i.setor}
            for i in sorted(self.itens.values(), key=lambda i: i.nome)
        ]

    def buscar_exato(self, texto: str) -> str | None:
        return self._exatos.get(normalizar(texto))

    def sugerir(self, texto: str, limite: int = 3) -> list[SugestaoExame]:
        n = normalizar(texto)
        if not n:
            return []
        resultados = process.extract(n, self._fuzzy_termos, scorer=fuzz.WRatio, limit=limite * 4)
        vistos: dict[str, SugestaoExame] = {}
        for termo, score, _ in resultados:
            codigo = self._exatos[termo]
            if codigo not in vistos:
                vistos[codigo] = SugestaoExame(codigo=codigo, nome=self.itens[codigo].nome, score=round(score, 1))
        return sorted(vistos.values(), key=lambda s: -s.score)[:limite]

    def mapear(self, exame: Exame, aprendidos: dict[str, str] | None = None) -> Exame:
        """Preenche código/nome do LIS e status de mapeamento no exame."""
        aprendidos = aprendidos or {}
        candidatos = [t for t in (exame.texto_original, exame.nome_interpretado) if t]

        for t in candidatos:
            codigo = aprendidos.get(normalizar(t))
            if codigo and codigo in self.itens:
                return self._aplicar(exame, codigo, 100.0, "ok")
        for t in candidatos:
            codigo = self.buscar_exato(t)
            if codigo:
                return self._aplicar(exame, codigo, 100.0, "ok")

        melhores: list[SugestaoExame] = []
        for t in candidatos:
            melhores.extend(self.sugerir(t))
        # mantém a melhor nota por código
        por_codigo: dict[str, SugestaoExame] = {}
        for s in melhores:
            if s.codigo not in por_codigo or s.score > por_codigo[s.codigo].score:
                por_codigo[s.codigo] = s
        sugestoes = sorted(por_codigo.values(), key=lambda s: -s.score)[:3]
        exame.sugestoes = sugestoes
        if sugestoes and sugestoes[0].score >= config.SCORE_OK:
            return self._aplicar(exame, sugestoes[0].codigo, sugestoes[0].score, "ok", sugestoes)
        if sugestoes and sugestoes[0].score >= config.SCORE_REVISAR:
            return self._aplicar(exame, sugestoes[0].codigo, sugestoes[0].score, "revisar", sugestoes)
        exame.codigo_lis = ""
        exame.nome_lis = ""
        exame.score = sugestoes[0].score if sugestoes else 0.0
        exame.status_mapeamento = "nao_encontrado"
        return exame

    def _aplicar(self, exame: Exame, codigo: str, score: float, status: str, sugestoes=None) -> Exame:
        exame.codigo_lis = codigo
        exame.nome_lis = self.itens[codigo].nome
        exame.score = score
        exame.status_mapeamento = status  # type: ignore[assignment]
        if sugestoes is not None:
            exame.sugestoes = sugestoes
        return exame
