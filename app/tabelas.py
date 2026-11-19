"""Leitura das bases do laboratório (exames, fontes pagadoras, médicos).

Aceita CSV (separador ; , ou tab, UTF-8 ou Latin-1) e Excel (.xlsx), com
nomes de coluna flexíveis: "Mnemônico", "MNEMONICO" e "mnemonico" são a mesma
coluna, e cada campo aceita vários apelidos (ver `campo`).
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .catalogo import normalizar


def _cabecalho(nome: str) -> str:
    return re.sub(r"\s+", "_", normalizar(str(nome or "")).replace("/", " "))


def ler_tabela(caminho: Path) -> list[dict[str, str]]:
    caminho = Path(caminho)
    if caminho.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(caminho, read_only=True, data_only=True)
        linhas = [[("" if v is None else str(v).strip()) for v in row] for row in wb.active.iter_rows(values_only=True)]
        wb.close()
    else:
        bruto = caminho.read_bytes()
        for cod in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = bruto.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        primeira = texto.splitlines()[0] if texto else ""
        sep = max((";", ",", "\t", "|"), key=primeira.count)
        linhas = [[c.strip() for c in row] for row in csv.reader(io.StringIO(texto), delimiter=sep)]
    linhas = [l for l in linhas if any(l)]
    if not linhas:
        return []
    cab = [_cabecalho(c) for c in linhas[0]]
    return [{cab[i]: (l[i] if i < len(l) else "") for i in range(len(cab)) if cab[i]} for l in linhas[1:]]


def campo(linha: dict[str, str], *apelidos: str) -> str:
    """Primeiro valor não vazio entre as colunas com esses nomes (já normalizados)."""
    for a in apelidos:
        v = linha.get(_cabecalho(a), "")
        if v:
            return v.strip()
    return ""


def inativo(linha: dict[str, str]) -> bool:
    """Linhas marcadas como inativas/bloqueadas na exportação são ignoradas."""
    v = normalizar(campo(linha, "ativo", "situacao", "situação", "status"))
    return v in ("n", "nao", "0", "false", "inativo", "bloqueado", "i", "cancelado")
