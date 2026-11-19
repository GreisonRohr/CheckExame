"""API web do CheckExame — leitura de requisições médicas e geração de O.S."""
from __future__ import annotations

import base64
import mimetypes
import secrets
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, db
from .catalogo import Catalogo
from .extractors import ErroExtracao, criar_extratores
from .lis import ErroLIS, montar_payload, obter_adaptador, validar_para_os
from .models import Requisicao

TAMANHO_MAXIMO = 20 * 1024 * 1024

app = FastAPI(title="CheckExame", version="0.1.0")
catalogo = Catalogo.carregar()
extratores = criar_extratores(catalogo)
db.init()


@app.middleware("http")
async def exigir_senha(request: Request, call_next):
    """Protege o site com usuário/senha quando CHECKEXAME_SENHA está definida."""
    if not config.SENHA or request.url.path == "/saude":
        return await call_next(request)
    cab = request.headers.get("authorization", "")
    if cab.startswith("Basic "):
        try:
            usuario, _, senha = base64.b64decode(cab[6:]).decode().partition(":")
        except Exception:  # noqa: BLE001
            usuario = senha = ""
        if secrets.compare_digest(usuario, config.USUARIO) and secrets.compare_digest(senha, config.SENHA):
            return await call_next(request)
    return Response("Acesso restrito", status_code=401, headers={"WWW-Authenticate": 'Basic realm="CheckExame"'})


@app.get("/saude")
def saude():
    return {"ok": True}


def _mapear(req: Requisicao) -> Requisicao:
    aprendidos = db.sinonimos_aprendidos()
    for ex in req.exames:
        catalogo.mapear(ex, aprendidos)
    return req


def _detectar_mime(arquivo: UploadFile) -> str:
    mime = arquivo.content_type or ""
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(arquivo.filename or "")[0] or "application/octet-stream"
    return mime


# --------------------------------------------------------------------- API
@app.get("/api/extratores")
def listar_extratores():
    out = []
    for e in extratores.values():
        ok, motivo = e.disponivel()
        out.append({"nome": e.nome, "descricao": e.descricao, "disponivel": ok, "motivo": motivo})
    return out


@app.get("/api/catalogo")
def listar_catalogo():
    return catalogo.listar()


@app.get("/api/catalogo/sugerir")
def sugerir(q: str):
    return [s.model_dump() for s in catalogo.sugerir(q, limite=8)]


@app.post("/api/leituras")
async def nova_leitura(
    extrator: str = Form("claude"),
    arquivo: UploadFile | None = File(None),
    texto: str = Form(""),
):
    if extrator not in extratores:
        raise HTTPException(400, f"Extrator desconhecido: {extrator}")
    if arquivo is not None and arquivo.filename:
        conteudo = await arquivo.read()
        mime = _detectar_mime(arquivo)
        nome = arquivo.filename
    elif texto.strip():
        conteudo, mime, nome = texto.encode(), "text/plain", "texto-colado.txt"
    else:
        raise HTTPException(400, "Envie um arquivo ou cole o texto da requisição.")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(413, "Arquivo maior que 20 MB.")

    sufixo = Path(nome).suffix or mimetypes.guess_extension(mime) or ""
    caminho = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{sufixo}"
    caminho.write_bytes(conteudo)

    inicio = time.monotonic()
    try:
        req = extratores[extrator].extrair(conteudo, mime, nome)
        status, erro = "lida", None
    except ErroExtracao as e:
        req, status, erro = None, "erro", str(e)
    duracao = int((time.monotonic() - inicio) * 1000)

    dados = _mapear(req).model_dump() if req else None
    leitura_id = db.criar_leitura(nome, str(caminho), mime, extrator, status, dados, erro, duracao)
    return db.obter_leitura(leitura_id)


@app.get("/api/leituras")
def listar_leituras():
    return db.listar_leituras()


@app.get("/api/leituras/{leitura_id}")
def obter_leitura(leitura_id: int):
    leitura = db.obter_leitura(leitura_id)
    if not leitura:
        raise HTTPException(404, "Leitura não encontrada.")
    return leitura


@app.get("/api/leituras/{leitura_id}/arquivo")
def arquivo_leitura(leitura_id: int):
    leitura = db.obter_leitura(leitura_id)
    if not leitura or not leitura.get("arquivo_path") or not Path(leitura["arquivo_path"]).exists():
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(leitura["arquivo_path"], media_type=leitura["mime"])


@app.put("/api/leituras/{leitura_id}")
def salvar_revisao(leitura_id: int, req: Requisicao):
    leitura = db.obter_leitura(leitura_id)
    if not leitura:
        raise HTTPException(404, "Leitura não encontrada.")
    if leitura["status"] == "os_gerada":
        raise HTTPException(409, "O.S. já gerada para esta leitura.")
    # Correções manuais de código viram sinônimos aprendidos
    for ex in req.exames:
        if ex.status_mapeamento == "manual" and ex.codigo_lis in catalogo.itens:
            ex.nome_lis = catalogo.itens[ex.codigo_lis].nome
            db.aprender_sinonimo(ex.texto_original, ex.codigo_lis)
    db.atualizar_leitura(leitura_id, dados=req.model_dump(), status="revisada", erro=None)
    return db.obter_leitura(leitura_id)


@app.post("/api/leituras/{leitura_id}/remapear")
def remapear(leitura_id: int, req: Requisicao):
    """Recalcula o mapeamento dos exames (após editar textos na revisão)."""
    return _mapear(req).model_dump()


@app.post("/api/leituras/{leitura_id}/os")
def gerar_os(leitura_id: int):
    leitura = db.obter_leitura(leitura_id)
    if not leitura or not leitura.get("dados"):
        raise HTTPException(404, "Leitura não encontrada.")
    if leitura["status"] == "os_gerada":
        raise HTTPException(409, f"O.S. {leitura['os_numero']} já gerada.")
    req = Requisicao.model_validate(leitura["dados"])
    pendencias = validar_para_os(req)
    if pendencias:
        raise HTTPException(422, {"pendencias": pendencias})
    payload = montar_payload(req, leitura_id)
    try:
        resultado = obter_adaptador().criar_os(payload)
    except ErroLIS as e:
        raise HTTPException(502, str(e)) from e
    db.atualizar_leitura(leitura_id, status="os_gerada", os_numero=resultado["os_numero"])
    return {"os_numero": resultado["os_numero"], "payload": payload}


@app.get("/api/estatisticas")
def estatisticas():
    """Acurácia: compara o que o extrator leu com o que foi revisado."""
    leituras = [db.obter_leitura(l["id"]) for l in db.listar_leituras(1000)]
    revisadas = [l for l in leituras if l["status"] in ("revisada", "os_gerada") and l["dados_originais"]]
    campos_total = campos_iguais = exames_total = exames_ok = 0
    for l in revisadas:
        orig, final = l["dados_originais"], l["dados"]
        for grupo in ("paciente", "convenio", "medico"):
            for k, v in (final.get(grupo) or {}).items():
                if v:
                    campos_total += 1
                    campos_iguais += int((orig.get(grupo) or {}).get(k, "") == v)
        cod_orig = [e.get("codigo_lis") for e in orig.get("exames", [])]
        for e in final.get("exames", []):
            exames_total += 1
            exames_ok += int(e.get("codigo_lis") in cod_orig)
    return {
        "leituras": len(leituras),
        "revisadas": len(revisadas),
        "erros": sum(1 for l in leituras if l["status"] == "erro"),
        "os_geradas": sum(1 for l in leituras if l["status"] == "os_gerada"),
        "acuracia_campos": round(100 * campos_iguais / campos_total, 1) if campos_total else None,
        "acuracia_exames": round(100 * exames_ok / exames_total, 1) if exames_total else None,
    }


# --------------------------------------------------------------------- front
app.mount("/", StaticFiles(directory=config.BASE_DIR / "static", html=True), name="static")
