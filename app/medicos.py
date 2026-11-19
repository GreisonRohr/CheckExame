"""Base de médicos e outros profissionais (CRM, CRO, COREN...) e comparação com a requisição.

Ordem de busca:
1. conselho + número + UF iguais                          -> ok
2. número igual (UF/conselho ausente ou diferente):
   um só candidato com nome parecido                      -> ok; senão -> revisar
3. sem número: nome muito parecido com um só profissional -> revisar (homônimos são comuns)
4. nada encontrado                                        -> nao_encontrado (segue com o que foi lido)
Quando confirmado, nome/conselho/número/UF passam a ser os da base.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from . import config
from .catalogo import normalizar
from .models import Medico

UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
TITULOS = re.compile(r"^(dr|dra|dr\.|dra\.|doutor|doutora|prof|profa)\s+", re.I)


@dataclass
class Profissional:
    codigo: str
    nome: str
    conselho: str
    numero: str
    uf: str
    especialidade: str = ""

    def resumo(self) -> dict:
        return {"codigo": self.codigo, "nome": self.nome, "conselho": self.conselho, "numero": self.numero,
                "uf": self.uf, "especialidade": self.especialidade}


def _num(v: str) -> str:
    return re.sub(r"\D", "", v or "").lstrip("0")


def _nome(v: str) -> str:
    return normalizar(TITULOS.sub("", (v or "").strip()))


class Medicos:
    def __init__(self, itens: list[Profissional]):
        self.itens = itens
        self._por_numero: dict[str, list[Profissional]] = {}
        for p in itens:
            if _num(p.numero):
                self._por_numero.setdefault(_num(p.numero), []).append(p)
        self._nomes = [_nome(p.nome) for p in itens]

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Medicos":
        from .tabelas import campo, inativo, ler_tabela

        caminho = caminho or config.MEDICOS_PATH
        if not Path(caminho).exists():
            return cls([])
        itens = []
        for r in ler_tabela(caminho):
            nome = campo(r, "nome", "nome_medico", "medico", "profissional", "nome_profissional", "solicitante")
            numero = campo(r, "numero", "numero_conselho", "crm", "registro", "nr_conselho", "num_conselho", "conselho_numero")
            if not nome or inativo(r):
                continue
            conselho = campo(r, "conselho", "tipo_conselho", "sigla_conselho") or "CRM"
            # aceita "CRM" ou "CRM/RS" na coluna conselho, e "12345/RS" no número
            uf = campo(r, "uf", "uf_conselho", "estado", "uf_crm").upper()
            if not uf and (m := re.search(r"\b([A-Z]{2})\b\s*$", numero.upper())) and m.group(1) in UFS:
                uf = m.group(1)
            if m := re.match(r"([A-Za-z]+)\s*[-/]?\s*([A-Za-z]{2})?$", conselho.strip()):
                conselho = m.group(1)
                uf = uf or (m.group(2) or "").upper()
            itens.append(Profissional(
                codigo=campo(r, "codigo", "cod_medico", "id", "codigo_medico"),
                nome=nome.strip(), conselho=conselho.upper(), numero=_num(numero), uf=uf,
                especialidade=campo(r, "especialidade", "especialidades"),
            ))
        return cls(itens)

    def __len__(self):
        return len(self.itens)

    # ------------------------------------------------------------------ busca
    def buscar(self, termo: str, limite: int = 8) -> list[dict]:
        """Busca por número do conselho ou nome (para a tela de revisão)."""
        if _num(termo) and len(_num(termo)) >= 3:
            achados = [p for n, ps in self._por_numero.items() if n.startswith(_num(termo)) for p in ps]
            return [p.resumo() for p in achados[:limite]]
        if len(_nome(termo)) < 3:
            return []
        res = process.extract(_nome(termo), self._nomes, scorer=fuzz.WRatio, limit=limite, score_cutoff=60)
        return [self.itens[i].resumo() for _, _, i in res]

    def comparar(self, med: Medico) -> Medico:
        """Compara o médico lido com a base e preenche situação, sugestões e dados corretos."""
        if not self.itens:
            med.situacao = ""
            return med
        if not med.lido:
            med.lido = " ".join(x for x in (med.nome, med.conselho, med.numero_conselho, med.uf_conselho) if x)
        numero, nome = _num(med.numero_conselho), _nome(med.nome)
        conselho, uf = (med.conselho or "CRM").upper(), (med.uf_conselho or "").upper()

        if numero and numero in self._por_numero:
            candidatos = self._por_numero[numero]
            exatos = [p for p in candidatos if p.conselho == conselho and (not uf or p.uf == uf)]
            if len(exatos) == 1 and (uf or len(candidatos) == 1):
                return self._aplicar(med, exatos[0], "ok")
            parecidos = [p for p in candidatos if nome and fuzz.WRatio(nome, _nome(p.nome)) >= 85]
            if len(parecidos) == 1:
                return self._aplicar(med, parecidos[0], "ok")
            med.sugestoes = [p.resumo() for p in (exatos or candidatos)[:5]]
            med.situacao = "revisar"
            return med

        if nome:
            res = process.extract(nome, self._nomes, scorer=fuzz.WRatio, limit=5, score_cutoff=80)
            if res:
                med.sugestoes = [self.itens[i].resumo() for _, _, i in res]
                med.situacao = "revisar"
                return med
        med.sugestoes = []
        med.situacao = "nao_encontrado"
        return med

    @staticmethod
    def _aplicar(med: Medico, p: Profissional, situacao: str) -> Medico:
        med.codigo, med.nome, med.conselho = p.codigo, p.nome, p.conselho
        med.numero_conselho, med.uf_conselho = p.numero, p.uf
        med.situacao, med.sugestoes = situacao, []
        return med
