"""Persistência simples em SQLite (leituras e sinônimos aprendidos)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config
from .catalogo import normalizar

SCHEMA = """
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    arquivo_nome TEXT,
    arquivo_path TEXT,
    mime TEXT,
    extrator TEXT NOT NULL,
    status TEXT NOT NULL,          -- lida | revisada | os_gerada | erro
    dados_json TEXT,
    dados_originais_json TEXT,     -- o que o extrator devolveu, para medir acurácia
    erro TEXT,
    os_numero TEXT,
    duracao_ms INTEGER
);
CREATE TABLE IF NOT EXISTS sinonimos_convenio (
    texto_normalizado TEXT PRIMARY KEY,
    codigo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sinonimos (
    texto_normalizado TEXT PRIMARY KEY,
    codigo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conexao():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with conexao() as con:
        con.executescript(SCHEMA)


def criar_leitura(arquivo_nome, arquivo_path, mime, extrator, status, dados=None, erro=None, duracao_ms=None) -> int:
    dados_json = json.dumps(dados, ensure_ascii=False) if dados is not None else None
    with conexao() as con:
        cur = con.execute(
            """INSERT INTO leituras (criado_em, atualizado_em, arquivo_nome, arquivo_path, mime, extrator,
                                     status, dados_json, dados_originais_json, erro, duracao_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_agora(), _agora(), arquivo_nome, arquivo_path, mime, extrator, status, dados_json, dados_json, erro, duracao_ms),
        )
        return cur.lastrowid


def atualizar_leitura(leitura_id: int, **campos):
    if "dados" in campos:
        campos["dados_json"] = json.dumps(campos.pop("dados"), ensure_ascii=False)
    campos["atualizado_em"] = _agora()
    sets = ", ".join(f"{k} = ?" for k in campos)
    with conexao() as con:
        con.execute(f"UPDATE leituras SET {sets} WHERE id = ?", (*campos.values(), leitura_id))


def _row(row) -> dict:
    d = dict(row)
    for k in ("dados_json", "dados_originais_json"):
        d[k.replace("_json", "")] = json.loads(d.pop(k)) if d.get(k) else None
    return d


def obter_leitura(leitura_id: int) -> dict | None:
    with conexao() as con:
        row = con.execute("SELECT * FROM leituras WHERE id = ?", (leitura_id,)).fetchone()
        return _row(row) if row else None


def listar_leituras(limite: int = 100) -> list[dict]:
    with conexao() as con:
        rows = con.execute(
            "SELECT id, criado_em, arquivo_nome, extrator, status, os_numero, duracao_ms, erro, dados_json "
            "FROM leituras ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        dados = json.loads(d.pop("dados_json")) if d.get("dados_json") else {}
        d["paciente"] = (dados.get("paciente") or {}).get("nome", "")
        d["qtd_exames"] = len(dados.get("exames") or [])
        out.append(d)
    return out


def sinonimos_aprendidos() -> dict[str, str]:
    with conexao() as con:
        return {r["texto_normalizado"]: r["codigo"] for r in con.execute("SELECT * FROM sinonimos")}


def aprender_sinonimo(texto: str, codigo: str):
    n = normalizar(texto)
    if not n or not codigo:
        return
    with conexao() as con:
        con.execute(
            "INSERT INTO sinonimos (texto_normalizado, codigo, criado_em) VALUES (?,?,?) "
            "ON CONFLICT(texto_normalizado) DO UPDATE SET codigo = excluded.codigo",
            (n, codigo, _agora()),
        )


def convenios_aprendidos() -> dict[str, str]:
    with conexao() as con:
        return {r["texto_normalizado"]: r["codigo"] for r in con.execute("SELECT * FROM sinonimos_convenio")}


def aprender_convenio(texto: str, codigo: str):
    n = normalizar(texto)
    if not n or not codigo:
        return
    with conexao() as con:
        con.execute(
            "INSERT INTO sinonimos_convenio (texto_normalizado, codigo, criado_em) VALUES (?,?,?) "
            "ON CONFLICT(texto_normalizado) DO UPDATE SET codigo = excluded.codigo",
            (n, codigo, _agora()),
        )
