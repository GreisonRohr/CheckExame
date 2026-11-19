"""Extrator baseado no Claude (visão + saída estruturada).

Lê fotos, digitalizações e PDFs de requisições — inclusive manuscritas — e
devolve um JSON validado contra o schema abaixo.
"""
from __future__ import annotations

import base64
import io
import json
import os

import anthropic

from .. import config
from ..models import Requisicao
from .base import ErroExtracao, Extrator

MIME_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
LADO_MAXIMO_PX = 2000

_S = {"type": "string"}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA = _obj(
    {
        "paciente": _obj(
            {k: _S for k in ("nome", "data_nascimento", "sexo", "cpf", "cns", "telefone", "nome_mae")}
        ),
        "convenio": _obj(
            {k: _S for k in ("nome", "plano", "carteirinha", "validade_carteirinha", "numero_guia")}
        ),
        "medico": _obj({k: _S for k in ("nome", "conselho", "numero_conselho", "uf_conselho")}),
        "data_solicitacao": _S,
        "cid": _S,
        "indicacao_clinica": _S,
        "urgente": {"type": "boolean"},
        "exames": {
            "type": "array",
            "items": _obj({"texto_original": _S, "nome_interpretado": _S, "observacao": _S}),
        },
        "observacoes": _S,
        "legibilidade": {"type": "string", "enum": ["boa", "media", "ruim"]},
        "campos_incertos": {"type": "array", "items": _S},
        "alertas": {"type": "array", "items": _S},
    }
)

SYSTEM = """Você é um assistente de recepção de laboratório de análises clínicas no Brasil.
Sua tarefa é transcrever requisições médicas (pedidos de exame) — impressas, digitadas ou
manuscritas — para um formulário estruturado que será usado para abrir a ordem de serviço (O.S.)
no sistema do laboratório (LIS).

Regras:
- Transcreva apenas o que está no documento. Nunca invente dados. Campo ausente ou ilegível = "".
- Datas no formato DD/MM/AAAA. CPF apenas com dígitos (11). Sexo: "M", "F" ou "".
- Convênio: nome da operadora/plano como escrito; "PARTICULAR" se o pedido indicar particular;
  "SUS" se for guia/receituário do SUS.
- Médico: nome, conselho (CRM, CRO, COREN etc.), número e UF — geralmente no carimbo.
- Exames: um item por exame solicitado. Separe linhas como "Hemograma, glicose, ureia e creatinina"
  em itens distintos. Em "texto_original" copie exatamente como está escrito (com abreviações);
  em "nome_interpretado" escreva o nome completo usual do exame em português (ex.: "TGO" ->
  "Transaminase oxalacética (AST)", "EAS" -> "Urina tipo I"). Perfis/painéis (ex.: "lipidograma")
  ficam como um único item. Use "observacao" para jejum, material, lateralidade etc.
- "urgente" = true apenas se houver indicação explícita (urgente, URG, prioridade, emergência).
- "campos_incertos": caminhos dos campos que você leu com dúvida (ex.: "paciente.nome",
  "exames[2]", "medico.numero_conselho").
- "alertas": problemas que a recepção deve conferir: requisição sem assinatura/carimbo, data
  antiga (validade), paciente sem identificação, exame que não é de laboratório (imagem), letra
  ilegível em algum trecho, mais de um paciente, documento que não é requisição etc.
"""

INSTRUCAO = "Transcreva esta requisição médica para o formulário estruturado."


class ExtratorClaude(Extrator):
    nome = "claude"
    descricao = "Claude (visão) — imagens, PDFs e manuscritos"

    def __init__(self):
        self._client: anthropic.Anthropic | None = None

    def disponivel(self) -> tuple[bool, str]:
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return True, ""
        return False, "Defina ANTHROPIC_API_KEY no ambiente para usar o Claude."

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------------ entrada
    def _bloco_documento(self, conteudo: bytes, mime: str) -> dict:
        if mime == "application/pdf":
            return {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": base64.standard_b64encode(conteudo).decode()},
            }
        if mime.startswith("image/"):
            dados, mime_final = _preparar_imagem(conteudo, mime)
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_final,
                           "data": base64.standard_b64encode(dados).decode()},
            }
        if mime.startswith("text/"):
            return {"type": "text", "text": "Conteúdo da requisição:\n\n" + conteudo.decode("utf-8", "replace")}
        raise ErroExtracao(f"Tipo de arquivo não suportado: {mime}")

    # ------------------------------------------------------------------ chamada
    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Requisicao:
        ok, motivo = self.disponivel()
        if not ok:
            raise ErroExtracao(motivo)
        bloco = self._bloco_documento(conteudo, mime)
        try:
            resposta = self.client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": [bloco, {"type": "text", "text": INSTRUCAO}]}],
                output_config={
                    "effort": config.CLAUDE_EFFORT,
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                # se o modelo recusar por política, a API repete a chamada num modelo de fallback
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise ErroExtracao("Chave da API inválida (ANTHROPIC_API_KEY).") from e
        except anthropic.RateLimitError as e:
            raise ErroExtracao("Limite de requisições da API atingido; tente novamente em instantes.") from e
        except anthropic.BadRequestError as e:
            raise ErroExtracao(f"A API rejeitou o arquivo: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ErroExtracao(f"Erro da API ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ErroExtracao("Sem conexão com a API da Anthropic.") from e

        if resposta.stop_reason == "refusal":
            raise ErroExtracao("O modelo recusou processar este documento.")
        if resposta.stop_reason == "max_tokens":
            raise ErroExtracao("Resposta truncada (documento grande demais).")
        texto = next((b.text for b in resposta.content if b.type == "text"), None)
        if not texto:
            raise ErroExtracao("Resposta sem conteúdo.")
        try:
            return Requisicao.model_validate(json.loads(texto))
        except (json.JSONDecodeError, ValueError) as e:
            raise ErroExtracao(f"Resposta fora do formato esperado: {e}") from e


def _preparar_imagem(conteudo: bytes, mime: str) -> tuple[bytes, str]:
    """Corrige rotação EXIF (fotos de celular) e reduz imagens muito grandes."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if mime not in MIME_IMAGEM:
            raise ErroExtracao(f"Formato de imagem não suportado: {mime}")
        return conteudo, mime
    try:
        img = Image.open(io.BytesIO(conteudo))
        img = ImageOps.exif_transpose(img)
    except Exception as e:  # noqa: BLE001
        raise ErroExtracao(f"Não foi possível abrir a imagem ({mime}). Use JPG, PNG ou WEBP.") from e
    if max(img.size) > LADO_MAXIMO_PX:
        img.thumbnail((LADO_MAXIMO_PX, LADO_MAXIMO_PX))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"
