const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let catalogo = [];
let atual = null; // leitura em revisão

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const corpo = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const det = corpo?.detail;
    const msg = det?.pendencias ? det.pendencias.join("\n") : typeof det === "string" ? det : JSON.stringify(corpo);
    throw new Error(msg);
  }
  return corpo;
}
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ------------------------------------------------------------------ navegação
function mostrar(view) {
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  $$("nav button").forEach((b) => b.classList.toggle("ativo", b.dataset.view === view));
  if (view === "historico") carregarHistorico();
  carregarStats();
}
$$("nav button").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.view)));

async function carregarStats() {
  const s = await api("/api/estatisticas");
  const p = (v) => (v == null ? "—" : `${v}%`);
  $("#stats").textContent = `${s.leituras} leituras · ${s.os_geradas} O.S. · acerto campos ${p(s.acuracia_campos)} · acerto exames ${p(s.acuracia_exames)}`;
}

// ------------------------------------------------------------------ upload
async function init() {
  const [ext, cat] = await Promise.all([api("/api/extratores"), api("/api/catalogo")]);
  catalogo = cat;
  $("#dl-catalogo").innerHTML = cat.map((c) => `<option value="${esc(c.codigo)}">${esc(c.nome)}</option>`).join("");
  const sel = $("#sel-extrator");
  sel.innerHTML = ext.map((e) => `<option value="${e.nome}" ${e.disponivel ? "" : "data-off"}>${esc(e.descricao)}${e.disponivel ? "" : " (indisponível)"}</option>`).join("");
  const primeiroOk = ext.find((e) => e.disponivel);
  if (primeiroOk) sel.value = primeiroOk.nome;
  const aviso = () => {
    const e = ext.find((x) => x.nome === sel.value);
    $("#extrator-aviso").textContent = e && !e.disponivel ? e.motivo : "";
  };
  sel.addEventListener("change", aviso);
  aviso();
  carregarStats();
}

const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("sobre"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("sobre")));
dz.addEventListener("drop", (e) => {
  e.preventDefault();
  $("#arquivo").files = e.dataTransfer.files;
  $("#arquivo-nome").textContent = e.dataTransfer.files[0]?.name || "";
});
$("#arquivo").addEventListener("change", (e) => ($("#arquivo-nome").textContent = e.target.files[0]?.name || ""));

$("#form-upload").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  if (!$("#arquivo").files.length) fd.delete("arquivo");
  $("#btn-ler").disabled = true;
  $("#lendo").hidden = false;
  try {
    const leitura = await api("/api/leituras", { method: "POST", body: fd });
    e.target.reset();
    $("#arquivo-nome").textContent = "";
    abrirRevisao(leitura);
  } catch (err) {
    alert("Erro: " + err.message);
  } finally {
    $("#btn-ler").disabled = false;
    $("#lendo").hidden = true;
  }
});

// ------------------------------------------------------------------ revisão
function getPath(obj, path) { return path.split(".").reduce((o, k) => o?.[k], obj); }
function setPath(obj, path, val) {
  const ks = path.split(".");
  const last = ks.pop();
  ks.reduce((o, k) => (o[k] ??= {}), obj)[last] = val;
}

function abrirRevisao(leitura) {
  atual = leitura;
  mostrar("revisao");
  $("#rev-titulo").textContent = `#${leitura.id} · ${leitura.arquivo_nome || ""} · ${leitura.extrator}${leitura.duracao_ms ? ` · ${(leitura.duracao_ms / 1000).toFixed(1)}s` : ""}`;
  const st = $("#rev-status");
  st.textContent = leitura.os_numero ? `O.S. ${leitura.os_numero}` : leitura.status;
  st.className = `badge st-${leitura.status}`;

  // documento
  const prev = $("#doc-preview");
  const url = `/api/leituras/${leitura.id}/arquivo`;
  if (leitura.mime?.startsWith("image/")) {
    prev.innerHTML = `<img src="${url}" alt="requisição">`;
    $("img", prev).addEventListener("click", (e) => e.target.classList.toggle("zoom"));
  } else if (leitura.mime === "application/pdf") {
    prev.innerHTML = `<iframe src="${url}"></iframe>`;
  } else {
    fetch(url).then((r) => r.text()).then((t) => (prev.innerHTML = `<pre>${esc(t)}</pre>`));
  }

  const d = leitura.dados || { paciente: {}, convenio: {}, medico: {}, exames: [] };
  const incertos = new Set(d.campos_incertos || []);
  $$("[data-c]").forEach((el) => {
    const v = getPath(d, el.dataset.c);
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v ?? "";
    el.classList.toggle("incerto", incertos.has(el.dataset.c));
  });

  const alertas = [];
  if (leitura.erro) alertas.push(`<div class="alerta erro">${esc(leitura.erro)}</div>`);
  if (d.legibilidade === "ruim") alertas.push(`<div class="alerta">Legibilidade ruim — confira tudo com atenção.</div>`);
  (d.alertas || []).forEach((a) => alertas.push(`<div class="alerta">${esc(a)}</div>`));
  if (incertos.size) alertas.push(`<div class="alerta">Campos lidos com dúvida estão destacados em amarelo.</div>`);
  $("#rev-alertas").innerHTML = alertas.join("");
  $("#rev-msg").innerHTML = "";

  renderExames(d.exames || [], incertos);
  const travado = leitura.status === "os_gerada";
  $$("#form-rev input, #form-rev select, #form-rev textarea, #form-rev button").forEach((el) => (el.disabled = travado));
}

function renderExames(exames, incertos = new Set()) {
  const tb = $("#tab-exames tbody");
  tb.innerHTML = "";
  exames.forEach((ex, i) => tb.appendChild(linhaExame(ex, incertos.has(`exames[${i}]`))));
}

function linhaExame(ex, incerto = false) {
  const tr = document.createElement("tr");
  tr._ex = structuredClone(ex);
  const sugs = (ex.status_mapeamento !== "ok" && ex.status_mapeamento !== "manual" ? ex.sugestoes || [] : [])
    .map((s) => `<button type="button" data-cod="${esc(s.codigo)}" title="score ${s.score}">${esc(s.codigo)} · ${esc(s.nome)}</button>`).join("");
  tr.innerHTML = `
    <td class="orig ${incerto ? "incerto" : ""}">
      <input class="ex-texto" value="${esc(ex.texto_original)}">
      ${ex.nome_interpretado && ex.nome_interpretado !== ex.texto_original ? `<small>lido como: ${esc(ex.nome_interpretado)}</small>` : ""}
      ${ex.observacao ? `<small>obs: ${esc(ex.observacao)}</small>` : ""}
    </td>
    <td><input class="ex-cod" list="dl-catalogo" value="${esc(ex.codigo_lis)}"></td>
    <td><span class="ex-nome">${esc(ex.nome_lis)}</span>${sugs ? `<div class="sugs">${sugs}</div>` : ""}</td>
    <td><span class="badge st-${ex.status_mapeamento}">${statusTxt(ex)}</span></td>
    <td><button type="button" class="rm" title="remover">×</button></td>`;

  const definirCodigo = (cod) => {
    const item = catalogo.find((c) => c.codigo.toLowerCase() === cod.trim().toLowerCase());
    tr._ex.codigo_lis = item ? item.codigo : cod.trim();
    tr._ex.nome_lis = item ? item.nome : "";
    tr._ex.status_mapeamento = item ? "manual" : "nao_encontrado";
    tr._ex.score = item ? 100 : 0;
    tr.replaceWith(linhaExame(tr._ex));
  };
  $(".ex-cod", tr).addEventListener("change", (e) => definirCodigo(e.target.value));
  $$(".sugs button", tr).forEach((b) => b.addEventListener("click", () => definirCodigo(b.dataset.cod)));
  $(".rm", tr).addEventListener("click", () => tr.remove());
  $(".ex-texto", tr).addEventListener("change", async (e) => {
    tr._ex.texto_original = e.target.value;
    tr._ex.nome_interpretado = "";
    const r = await api(`/api/leituras/${atual.id}/remapear`, jsonOpts("POST", { exames: [tr._ex] }));
    tr.replaceWith(linhaExame(r.exames[0]));
  });
  return tr;
}

function statusTxt(ex) {
  return { ok: "ok", revisar: `revisar (${Math.round(ex.score)})`, nao_encontrado: "não encontrado", manual: "manual" }[ex.status_mapeamento] || ex.status_mapeamento;
}

$("#btn-add-exame").addEventListener("click", () => {
  const tr = linhaExame({ texto_original: "", codigo_lis: "", nome_lis: "", status_mapeamento: "nao_encontrado", sugestoes: [] });
  $("#tab-exames tbody").appendChild(tr);
  $(".ex-texto", tr).focus();
});

function coletar() {
  const d = structuredClone(atual.dados || {});
  $$("[data-c]").forEach((el) => setPath(d, el.dataset.c, el.type === "checkbox" ? el.checked : el.value.trim()));
  d.exames = $$("#tab-exames tbody tr").map((tr) => tr._ex).filter((ex) => ex.texto_original || ex.codigo_lis);
  return d;
}

async function salvar() {
  const leitura = await api(`/api/leituras/${atual.id}`, jsonOpts("PUT", coletar()));
  atual = leitura;
  return leitura;
}

$("#btn-salvar").addEventListener("click", async () => {
  try {
    abrirRevisao(await salvar());
    $("#rev-msg").innerHTML = `<div class="alerta ok">Revisão salva.</div>`;
  } catch (err) {
    $("#rev-msg").innerHTML = `<div class="alerta erro">${esc(err.message)}</div>`;
  }
});

$("#btn-os").addEventListener("click", async () => {
  try {
    await salvar();
    const r = await api(`/api/leituras/${atual.id}/os`, { method: "POST" });
    abrirRevisao(await api(`/api/leituras/${atual.id}`));
    $("#rev-msg").innerHTML = `<div class="alerta ok">O.S. <strong>${esc(r.os_numero)}</strong> gerada.</div>
      <details><summary>Payload enviado ao LIS</summary><pre>${esc(JSON.stringify(r.payload, null, 2))}</pre></details>`;
  } catch (err) {
    $("#rev-msg").innerHTML = `<div class="alerta erro" style="white-space:pre-line">${esc(err.message)}</div>`;
  }
});

// ------------------------------------------------------------------ histórico
async function carregarHistorico() {
  const ls = await api("/api/leituras");
  $("#tab-hist tbody").innerHTML = ls.map((l) => `
    <tr data-id="${l.id}">
      <td>${l.id}</td><td>${esc(l.criado_em.replace("T", " "))}</td><td>${esc(l.arquivo_nome)}</td>
      <td>${esc(l.extrator)}</td><td>${esc(l.paciente)}</td><td>${l.qtd_exames}</td>
      <td>${l.duracao_ms != null ? (l.duracao_ms / 1000).toFixed(1) + "s" : ""}</td>
      <td><span class="badge st-${l.status}">${esc(l.status)}</span></td><td>${esc(l.os_numero || "")}</td>
    </tr>`).join("") || `<tr><td colspan="9" class="muted">Nenhuma leitura ainda.</td></tr>`;
  $$("#tab-hist tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", async () => abrirRevisao(await api(`/api/leituras/${tr.dataset.id}`))));
}

init();
