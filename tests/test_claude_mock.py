"""Valida a chamada ao Claude sem rede: intercepta o HTTP e devolve uma resposta simulada."""
import io
import json

import anthropic
import httpx2 as httpx
from PIL import Image

from app.extractors.claude_vision import ExtratorClaude

RESPOSTA = {
    "paciente": {"nome": "José da Silva", "data_nascimento": "02/05/1960", "sexo": "M", "cpf": "",
                 "cns": "", "telefone": "", "nome_mae": ""},
    "convenio": {"nome": "SUS", "plano": "", "carteirinha": "", "validade_carteirinha": "", "numero_guia": ""},
    "medico": {"nome": "Ana Costa", "conselho": "CRM", "numero_conselho": "54321", "uf_conselho": "RS"},
    "data_solicitacao": "18/11/2026", "cid": "", "indicacao_clinica": "", "urgente": False,
    "exames": [{"texto_original": "HMG", "nome_interpretado": "Hemograma completo", "observacao": ""}],
    "observacoes": "", "legibilidade": "media", "campos_incertos": ["paciente.nome"], "alertas": [],
}


def test_extrator_claude_monta_requisicao_e_le_resposta(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["body"] = json.loads(request.content)
        capturado["beta"] = request.headers.get("anthropic-beta", "")
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(RESPOSTA)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    ext = ExtratorClaude()
    ext._client = anthropic.Anthropic(api_key="teste", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    img = io.BytesIO()
    Image.new("RGB", (3000, 1000), "white").save(img, format="PNG")
    req = ext.extrair(img.getvalue(), "image/png", "foto.png")

    assert req.paciente.nome == "José da Silva"
    assert req.exames[0].nome_interpretado == "Hemograma completo"
    body = capturado["body"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in capturado["beta"]
    bloco = body["messages"][0]["content"][0]
    assert bloco["type"] == "image" and bloco["source"]["media_type"] == "image/jpeg"
    # imagem reduzida para no máximo 2000 px
    import base64
    w, h = Image.open(io.BytesIO(base64.b64decode(bloco["source"]["data"]))).size
    assert max(w, h) == 2000
