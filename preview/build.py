"""Gera preview/index.html (página única) a partir do template, do catálogo e do exemplo."""
import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
linhas = csv.DictReader(open(RAIZ / "data/catalogo_exames.csv", encoding="utf-8"), delimiter=";")
cat = [[r["codigo"], r["nome"], r["sinonimos"], r["material"], r["setor"]] for r in linhas]
exemplo = (RAIZ / "exemplos/requisicao_impressa.txt").read_text(encoding="utf-8")
html = (RAIZ / "preview/template.html").read_text(encoding="utf-8")
html = html.replace("__CATALOGO__", json.dumps(cat, ensure_ascii=False)).replace("__EXEMPLO__", json.dumps(exemplo, ensure_ascii=False))
(RAIZ / "preview/index.html").write_text(html, encoding="utf-8")
print(f"preview/index.html: {len(html)} bytes, {len(cat)} exames")
