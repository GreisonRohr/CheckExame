# CheckExame

Leitura automática de requisições médicas (pedidos de exame) para gerar o cadastro
da O.S. no LIS do laboratório.

**Fase 1 (este repositório):** sistema web para testar leituras e importações,
revisar o resultado e medir a taxa de acerto.
**Fase 2:** integração com o LIS. A interface `AdaptadorLIS` já existe; falta
implementar o adaptador do seu LIS.

## Como funciona

```
 foto / PDF / texto ──► Extrator ──► Requisição estruturada ──► Mapeamento de exames ──► Revisão na tela ──► O.S. no LIS
                       (Claude ou     (paciente, convênio,       (catálogo do LIS +       (operador corrige)   (AdaptadorLIS)
                        regras)        médico, exames, CID)        sinônimos aprendidos)
```

1. **Extratores** (`app/extractors/`)
   - `claude`: usa o Claude com visão e saída estruturada (JSON Schema). Lê fotos de
     celular, digitalizações, PDFs e **requisições manuscritas**. Indica os campos lidos
     com dúvida, a legibilidade e alertas (sem carimbo, pedido vencido, exame de imagem…).
   - `texto`: regras/regex, sem IA. Para TXT e PDFs digitais (impressos pelo prontuário
     eletrônico). Serve também para testar o fluxo sem chave de API.
2. **Catálogo de exames** (`data/catalogo_exames.csv`): código do LIS, nome, sinônimos,
   material e setor. Cada exame lido é mapeado por correspondência exata (nome, código,
   sinônimos), depois por similaridade (`rapidfuzz`), e recebe status `ok`,
   `revisar` ou `não encontrado`, com sugestões.
3. **Aprendizado**: quando o operador corrige o código de um exame na revisão, o texto
   original vira sinônimo, e a próxima requisição com aquela escrita já vem mapeada.
4. **Revisão**: tela com o documento ao lado do formulário. Campos incertos aparecem
   em amarelo.
5. **Geração da O.S.**: valida os obrigatórios (nome, nascimento, exames com código) e
   envia um payload neutro ao adaptador do LIS.
6. **Estatísticas**: compara o que o extrator leu com o que foi revisado (acerto de
   campos e de exames), para avaliar a leitura antes de integrar.

## Rodando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...      # necessário para o extrator Claude
uvicorn app.main:app --reload --port 8000
```

Acesse http://localhost:8000. Há um exemplo em `exemplos/requisicao_impressa.txt`
(use o extrator "texto").

Testes: `pytest`

### Configuração (variáveis de ambiente — ver `.env.example`)

| Variável | Padrão | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chave da API da Anthropic |
| `CHECKEXAME_CLAUDE_MODEL` | `claude-opus-5-5` | Modelo usado na leitura |
| `CHECKEXAME_CLAUDE_EFFORT` | `high` | `low`…`max`. Menor = mais rápido e mais barato; manuscritos difíceis pedem `high` |
| `CHECKEXAME_SCORE_OK` / `_REVISAR` | 90 / 70 | Limiares do mapeamento automático |
| `CHECKEXAME_CATALOGO` | `data/catalogo_exames.csv` | Catálogo de exames do LIS |
| `CHECKEXAME_LIS_ADAPTER` | `mock` | `mock` (grava JSON em `data/os_geradas/`) ou `http` |
| `CHECKEXAME_LIS_URL` / `_TOKEN` | — | Endpoint e token para o adaptador `http` |

## Catálogo de exames

O CSV que acompanha o projeto é **um exemplo** com códigos mnemônicos fictícios.
Substitua-o pela exportação do cadastro de exames do seu LIS (separador `;`):

```
codigo;nome;sinonimos;material;setor
HMG;Hemograma completo;hemograma|hmg|hemo|eritrograma;Sangue EDTA;Hematologia
```

Quanto mais sinônimos e abreviações regionais (como os médicos da sua região escrevem),
melhor o mapeamento. Os sinônimos aprendidos na revisão ficam no banco
(`data/checkexame.db`, tabela `sinonimos`).

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/extratores` | Extratores e disponibilidade |
| `POST` | `/api/leituras` | Multipart: `extrator` + `arquivo` ou `texto`. Lê e mapeia |
| `GET` | `/api/leituras` / `/api/leituras/{id}` | Histórico / detalhe |
| `GET` | `/api/leituras/{id}/arquivo` | Documento original |
| `PUT` | `/api/leituras/{id}` | Salva a revisão (aprende sinônimos de correções manuais) |
| `POST` | `/api/leituras/{id}/os` | Gera a O.S. no LIS |
| `GET` | `/api/catalogo`, `/api/catalogo/sugerir?q=` | Catálogo e busca |
| `GET` | `/api/estatisticas` | Taxas de acerto |

Documentação interativa: http://localhost:8000/docs

## Próximos passos (integração com o LIS)

1. **Catálogo real**: importar os exames do LIS (código, nome, material) e manter a
   sincronização.
2. **Adaptador do LIS**: criar uma classe `AdaptadorLIS` em `app/lis/` conforme o que o
   LIS oferece:
   - API REST/SOAP → adaptar o `AdaptadorHTTP` ao formato do LIS;
   - acesso ao banco → inserir paciente, atendimento e itens da O.S.;
   - importação por arquivo (CSV/XML/HL7) → gerar o arquivo na pasta monitorada;
   - sem integração → automação de tela (RPA) como último recurso.
3. **Cadastro de paciente**: buscar o paciente existente (CPF / nome + nascimento)
   antes de criar um novo.
4. **Convênios e médicos**: mapear o nome lido para o código do convênio/plano e do
   médico no LIS (mesma lógica de sinônimos dos exames).
5. **Regras do laboratório**: validade do pedido, exames que exigem jejum/preparo,
   autorização de convênio, exames não realizados (terceirizados).
6. **Captura**: scanner na recepção (pasta monitorada) ou celular/tablet.
7. **LGPD**: as requisições contêm dados de saúde. Defina retenção dos arquivos em
   `data/uploads/`, controle de acesso (autenticação ainda não implementada) e avalie os
   termos de tratamento de dados com o provedor de IA antes de usar em produção.

## Estrutura

```
app/
  main.py              API FastAPI + arquivos estáticos
  models.py            Requisição, Paciente, Convênio, Médico, Exame
  catalogo.py          Catálogo de exames e mapeamento texto → código
  db.py                SQLite (leituras, sinônimos aprendidos)
  extractors/          claude_vision.py (IA) e texto.py (regras)
  lis/                 Adaptadores do LIS (mock, http)
static/                Interface web (HTML/JS puro)
data/catalogo_exames.csv
exemplos/              Requisições de exemplo
tests/
```

## Prévia no navegador (`preview/`)

`preview/index.html` é uma versão de página única do sistema, para testar sem
instalar nada: roda inteira no navegador e, publicada no claude.ai, faz a leitura
com Claude usando a conta de quem abre a página. Histórico e correções ficam no
navegador e a O.S. é simulada. É gerada a partir de `preview/template.html`,
do catálogo e do exemplo:

```bash
python preview/build.py
```
