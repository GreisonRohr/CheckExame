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

### Testar pelo celular

**Na rede da sua casa/laboratório:** rode o servidor no computador com
`uvicorn app.main:app --host 0.0.0.0 --port 8000` e, no celular conectado ao mesmo
Wi-Fi, abra `http://IP-DO-COMPUTADOR:8000` (o IP aparece em `ipconfig` no Windows ou
`ip addr` no Linux).

**Na internet (Render, plano gratuito):**
1. Crie uma conta em https://render.com e conecte o GitHub.
2. *New → Web Service*, escolha o repositório `CheckExame` e o branch deste trabalho.
   O Render detecta o `Dockerfile`.
3. Em *Environment*, defina `ANTHROPIC_API_KEY` (sua chave da API) e
   `CHECKEXAME_SENHA` (senha de acesso ao site; o usuário é `checkexame`).
4. Abra o endereço `https://….onrender.com` gerado e entre com usuário e senha.

No plano gratuito o servidor "dorme" após um tempo sem uso (a primeira abertura
demora ~1 minuto) e o histórico é apagado a cada nova publicação. Para testes com
requisições reais, defina sempre a senha.

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
| `CHECKEXAME_SENHA` / `_USUARIO` | — / `checkexame` | Se a senha estiver definida, o site pede login |

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

## Integração com o Shift

O adaptador `shift` (`app/lis/shift.py`) segue o documento *Integra_RecebePedido_WSHIS
v1.3* e o XML de exemplo `ImportaPedidoSincRequest` (em `tests/dados/`):

1. Monta o XML `pedidoLab` (pedido, paciente, exames, médico em cada exame, dados
   cadastrais PLANO / CARTEIRA / DATAVALIDADECARTEIRA / GUIA, urgente 0/1).
2. Envia por SOAP, dentro de CDATA, em um dos dois modelos:
   - `integracao`: `ImportaPedidoSinc(IdIntegracao, Usuario, Senha, Pedidos)` (como no XML de exemplo);
   - `hospital`: `RecebePedido(idHospital, pedidoLab)` (como no documento v1.3).
3. Lê o `retornoLab`: número da O.S., códigos de barras e etiquetas das amostras, ou a
   descrição do erro.

Ative com `CHECKEXAME_LIS_ADAPTER=shift`. Sem `CHECKEXAME_SHIFT_URL`, funciona em
**modo arquivo**: gera o envelope em `data/os_geradas/<pedido>.xml` sem enviar nada,
para conferir ou testar no SoapUI. Na tela de revisão, o botão **Ver XML do Shift**
mostra o envelope com as pendências.

Regras aplicadas:
- **Código do pedido / O.S.**: `CKX` + data da leitura + número da leitura (único e estável).
- **Código do paciente**: o informado; senão o CPF; senão `CKXP<leitura>`.
- **Convênio**: o nome lido é convertido para código pela tabela `data/convenios.csv`
  (exemplo; trocar pela tabela do Shift) ou usa `CHECKEXAME_SHIFT_CONVENIO_PADRAO`.
- **Exames**: código e material vêm do catálogo. No catálogo de exemplo, HEMO, GLIC, UREI,
  CREA, HIV, AGHBS, HBS e HCV já usam os códigos do XML de exemplo da Shift; os demais
  são fictícios.
- **Obrigatórios do Shift**: sexo M/F, data de nascimento válida, convênio, posto.

Variáveis: ver `.env.example` (seção Shift).

A integração de **resultados** (`ExportaResultados`, documento *Integra_EnvioResultados*)
ainda não foi implementada; ela permite buscar no Shift os resultados das O.S. criadas.

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
