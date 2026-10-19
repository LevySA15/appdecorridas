"use strict";
// Painel do dono: uma página só, sem etapa de compilação. Toda a regra está na API do servidor (rotas de administrador).
// Regra de ouro: texto vindo da API só entra na página por esc()/money()/when()/attr(), nunca como HTML.

const TOKEN_KEY = "painel-token";

function esc(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function attr(valor) { return esc(valor); }
function raw(html) { return html; }
function money(centavos) { return "R$ " + (Number(centavos || 0) / 100).toFixed(2).replace(".", ","); }
function when(segundos) { return segundos ? new Date(segundos * 1000).toLocaleString("pt-BR") : "–"; }

const CANCELADO = Symbol("cancelado");   // o administrador desistiu no prompt: nada foi feito

const TELAS = {
  cadastros: "Cadastros", corridas: "Corridas", passageiros: "Passageiros", dinheiro: "Dinheiro",
  devedores: "Devedores", recursos: "Recursos", alertas: "Alertas", parametros: "Parâmetros", registro: "Registro",
};
let telaAtual = "cadastros";
let filtros = { cadastros: "pending", corridas: "", passageiros: "" };

function el(id) { return document.getElementById(id); }
function aviso(texto, ok) { el("aviso").textContent = texto || ""; el("aviso").className = ok ? "ok" : ""; }
function sair() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) fetch("/v1/auth/logout", { method: "POST", headers: { Authorization: "Bearer " + token } }).catch(() => {});   // encerra a sessão no servidor
  sessionStorage.removeItem(TOKEN_KEY);
  mostrarEntrada();
}

async function api(caminho, opcoes = {}) {
  const cabecalhos = { "Content-Type": "application/json" };
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) cabecalhos.Authorization = "Bearer " + token;
  const resposta = await fetch(caminho, { ...opcoes, headers: cabecalhos, body: opcoes.json !== undefined ? JSON.stringify(opcoes.json) : undefined });
  if (resposta.status === 401 && token) { sair(); throw new Error("Sua sessão acabou. Entre de novo."); }
  if (resposta.status === 204) return null;
  const corpo = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error((corpo.error && corpo.error.message) || "Algo deu errado (" + resposta.status + ").");
  return corpo;
}

function tabela(cabecalhos, linhas) {
  if (!linhas.length) return '<p class="suave">Nada por aqui.</p>';
  const topo = cabecalhos.map((h) => `<th>${esc(h)}</th>`).join("");
  return `<table><thead><tr>${raw(topo)}</tr></thead><tbody>${raw(linhas.map((l) => "<tr>" + l.map((c) => `<td>${raw(c)}</td>`).join("") + "</tr>").join(""))}</tbody></table>`;
}
function botao(acao, id, texto, classe = "", extra = "") {
  return `<button class="${attr(classe)}" data-act="${attr(acao)}" data-id="${attr(id)}" ${raw(extra)}>${esc(texto)}</button>`;
}

// ---------- entrada ----------
function mostrarEntrada() {
  el("menu").hidden = true; el("sair").hidden = true; el("tela").hidden = true; el("detalhe").hidden = true;
  el("entrada").hidden = false;
  el("entrada").innerHTML = `<h2>Entrar</h2>
    <p>Telefone do administrador:</p>
    <input id="telefone" type="tel" placeholder="75 99999-0000" autocomplete="tel">
    <button id="pedir-codigo">Receber código</button>
    <div id="passo-codigo" hidden>
      <p>Código recebido:</p>
      <input id="codigo" inputmode="numeric" maxlength="6" autocomplete="one-time-code">
      <button id="entrar">Entrar</button>
      <button id="pegar-codigo" hidden>Pegar o código (só em desenvolvimento)</button>
    </div>`;
  el("pedir-codigo").onclick = pedirCodigo;
  el("entrar").onclick = entrar;
  el("pegar-codigo").onclick = pegarCodigo;
}
async function pedirCodigo() {
  aviso("");
  try {
    await api("/v1/auth/code", { method: "POST", json: { phone: el("telefone").value } });
    el("passo-codigo").hidden = false;
    el("pegar-codigo").hidden = false;
    aviso("Código enviado.", true);
  } catch (erro) { aviso(erro.message); }
}
async function pegarCodigo() {
  try {
    const corpo = await api("/v1/dev/otp?phone=" + encodeURIComponent(el("telefone").value));
    el("codigo").value = corpo.code;
  } catch (erro) { aviso("Isso só existe em desenvolvimento. " + erro.message); }
}
async function entrar() {
  aviso("");
  try {
    const corpo = await api("/v1/auth/verify", { method: "POST", json: { phone: el("telefone").value, code: el("codigo").value, role: "admin", device: "painel" } });
    sessionStorage.setItem(TOKEN_KEY, corpo.token);
    iniciar();
  } catch (erro) { aviso(erro.message); }
}

// ---------- telas ----------
const VISOES = {
  async cadastros() {
    const estado = filtros.cadastros;
    const lista = await api("/v1/admin/riders?status=" + encodeURIComponent(estado) + "&limit=100");
    const opcoes = ["pending", "approved", "blocked", "rejected"].map((s) => `<option value="${attr(s)}" ${raw(s === estado ? "selected" : "")}>${esc(s)}</option>`).join("");
    const linhas = lista.map((r) => [
      esc(r.name), esc(r.phone), esc(r.plate + " · " + r.moto_model), esc(r.status + (r.reason ? ": " + r.reason : "")),
      esc((r.cnh_expires_on || "–") + " / " + (r.crlv_expires_on || "–")),
      raw(["selfie", "cnh", "crlv"].map((k) => botao("doc", r.rider_id, k, "", `data-kind="${attr(k)}"`)).join(" ")),
      raw([r.status === "pending" ? botao("rider-approve", r.rider_id, "Aprovar", "bom") + botao("rider-reject", r.rider_id, "Recusar", "perigo") : "",
        r.status === "approved" ? botao("rider-block", r.rider_id, "Bloquear", "perigo") : "",
        r.status === "blocked" ? botao("rider-unblock", r.rider_id, "Liberar", "bom") : ""].join(" ")),
    ]);
    return `<p>Situação: <select id="filtro-cadastros">${raw(opcoes)}</select></p>` +
      tabela(["Nome", "Telefone", "Moto", "Situação", "CNH / documento", "Fotos", "Ações"], linhas);
  },
  async corridas() {
    const estado = filtros.corridas;
    const lista = await api("/v1/admin/rides?limit=100" + (estado ? "&state=" + encodeURIComponent(estado) : ""));
    const opcoes = ["", "searching", "accepted", "arrived", "in_progress", "completed", "cancelled", "no_rider"].map((s) => `<option value="${attr(s)}" ${raw(s === estado ? "selected" : "")}>${esc(s || "todas")}</option>`).join("");
    const linhas = lista.map((r) => [
      esc(when(r.created_at)), esc(r.state), esc(r.method), esc(money(r.price_cents)), esc(r.passenger_name), esc(r.rider_name || "–"),
      esc(r.pickup_text + " → " + r.dest_text), raw(botao("ride-detail", r.ride_id, "Detalhe")),
    ]);
    return `<p>Estado: <select id="filtro-corridas">${raw(opcoes)}</select></p>` +
      tabela(["Quando", "Estado", "Pagamento", "Preço", "Passageiro", "Motoqueiro", "Trajeto", ""], linhas);
  },
  async passageiros() {
    const lista = await api("/v1/admin/passengers?limit=100&q=" + encodeURIComponent(filtros.passageiros));
    const linhas = lista.map((p) => [
      esc(p.name), esc(p.phone), esc(p.is_blocked ? "bloqueado" : "ok"), esc(money(p.unpaid_cents)), esc(money(p.balance_cents)),
      raw(p.is_blocked ? botao("passenger-unblock", p.user_id, "Liberar", "bom") : botao("passenger-block", p.user_id, "Bloquear", "perigo")),
    ]);
    return `<p>Buscar: <input id="busca-passageiros" value="${attr(filtros.passageiros)}"> <button id="buscar-passageiros">Buscar</button></p>` +
      tabela(["Nome", "Telefone", "Situação", "Deve", "Saldo", "Ações"], linhas);
  },
  async dinheiro() {
    const d = await api("/v1/admin/money");
    const cartao = (titulo, valor) => `<div class="cartao"><span class="suave">${esc(titulo)}</span><b>${esc(valor)}</b></div>`;
    return `<div class="cartoes">${raw([
      cartao("Receita da empresa", money(d.company_cents)), cartao("Com o provedor de pagamento", money(d.provider_cents)),
      cartao("Ganho dos motoqueiros", money(d.riders_cents)), cartao("Saldos dos passageiros", money(d.passenger_balances_cents)),
      cartao("Taxas que motoqueiros devem", money(d.rider_debts_cents)), cartao("Passageiros devem (corridas e taxas)", money(d.passenger_unpaid_cents)),
      cartao("...das quais taxas de cancelamento", money(d.pending_fees_cents)), cartao("Livro-caixa fecha", d.ledger_balanced ? "sim" : "NÃO"),
    ].join(""))}</div><h3>Corridas por estado</h3><pre>${esc(JSON.stringify(d.rides_by_state, null, 2))}</pre>`;
  },
  async devedores() {
    const d = await api("/v1/admin/debtors");
    return "<h3>Motoqueiros</h3>" + tabela(["Nome", "Telefone", "Deve", "Reservado"], d.riders.map((r) => [esc(r.name), esc(r.phone), esc(money(r.cash_debt_cents)), esc(money(r.debt_reserved_cents))])) +
      "<h3>Passageiros</h3>" + tabela(["Nome", "Telefone", "Deve (total)", "...das quais taxa de cancelamento"], d.passengers.map((p) => [esc(p.name), esc(p.phone), esc(money(p.unpaid_cents)), esc(money(p.pending_fee_cents))]));
  },
  async recursos() {
    const lista = await api("/v1/admin/appeals?status=open&limit=100");
    return tabela(["Passageiro", "Motoqueiro", "Taxa", "Pedido", "Texto", "Ações"], lista.map((a) => [
      esc(a.passenger_name), esc(a.rider_name), esc(money(a.fee_cents)), esc(when(a.appealed_at)), esc(a.appeal_text),
      raw(botao("appeal-accept", a.ride_id, "Aceitar", "bom") + " " + botao("appeal-reject", a.ride_id, "Recusar", "perigo")),
    ]));
  },
  async alertas() {
    const abertos = await Promise.all(["open", "ok", "sos"].map((s) => api("/v1/admin/safety-alerts?limit=100&status=" + s)));
    const lista = abertos.flat();
    return tabela(["Quando", "Tipo", "Situação", "Passageiro", "Motoqueiro", "Placa", "Local", "Ações"], lista.map((a) => [
      esc(when(a.created_at)), esc(a.kind + (a.suspected_mock ? " (localização suspeita)" : "")), esc(a.status), esc(a.passenger_name),
      esc(a.rider_name), esc(a.plate), esc(a.lat == null ? "–" : a.lat.toFixed(5) + ", " + a.lng.toFixed(5)),
      raw(botao("alert-resolve", String(a.alert_id), "Resolver", "bom")),
    ]));
  },
  async parametros() {
    const todos = await api("/v1/admin/config");
    return "<p class=\"suave\">Cada bloco é um conjunto de números do sistema. Mude com cuidado: o servidor recusa o que não faz sentido.</p>" +
      Object.keys(todos).map((chave) => `<h3>${esc(chave)}</h3><textarea data-chave="${attr(chave)}">${esc(JSON.stringify(todos[chave], null, 2))}</textarea>${raw(botao("config-save", chave, "Salvar " + chave))}`).join("");
  },
  async registro() {
    const lista = await api("/v1/admin/actions?limit=100");
    return tabela(["Quando", "Quem", "Ação", "Em", "Detalhe"], lista.map((a) => [esc(when(a.at)), esc(a.admin_name), esc(a.action), esc(a.target_type + " " + a.target_id), esc(a.detail)]));
  },
};

async function mostrar(tela) {
  telaAtual = tela;
  aviso("");
  el("detalhe").hidden = true;
  for (const b of el("menu").children) b.classList.toggle("ativo", b.dataset.tela === tela);
  el("tela").hidden = false;
  el("tela").innerHTML = '<p class="suave">Carregando…</p>';
  try { el("tela").innerHTML = await VISOES[tela](); } catch (erro) { el("tela").innerHTML = ""; aviso(erro.message); }
}

// ---------- ações ----------
function perguntar(texto) { const r = window.prompt(texto); return r === null ? null : r.trim(); }
async function abrirDocumento(id, tipo) {
  const resposta = await fetch("/v1/riders/" + encodeURIComponent(id) + "/documents/" + encodeURIComponent(tipo), { headers: { Authorization: "Bearer " + sessionStorage.getItem(TOKEN_KEY) } });
  if (!resposta.ok) throw new Error("Não consegui abrir o documento.");
  window.open(URL.createObjectURL(await resposta.blob()), "_blank", "noopener");
}
const ACOES = {
  "rider-approve": (id) => api("/v1/admin/riders/" + encodeURIComponent(id) + "/approve", { method: "POST" }),
  "rider-reject": (id) => { const m = perguntar("Motivo da recusa:"); return m ? api("/v1/admin/riders/" + encodeURIComponent(id) + "/reject", { method: "POST", json: { reason: m } }) : CANCELADO; },
  "rider-block": (id) => { const m = perguntar("Motivo do bloqueio:"); return m ? api("/v1/admin/riders/" + encodeURIComponent(id) + "/block", { method: "POST", json: { reason: m } }) : CANCELADO; },
  "rider-unblock": (id) => api("/v1/admin/riders/" + encodeURIComponent(id) + "/unblock", { method: "POST" }),
  "passenger-block": (id) => { const m = perguntar("Motivo do bloqueio:"); return m ? api("/v1/admin/passengers/" + encodeURIComponent(id) + "/block", { method: "POST", json: { reason: m } }) : CANCELADO; },
  "passenger-unblock": (id) => api("/v1/admin/passengers/" + encodeURIComponent(id) + "/unblock", { method: "POST" }),
  "appeal-accept": (id) => { const n = perguntar("Nota (pode ficar vazia):"); return n === null ? CANCELADO : api("/v1/admin/appeals/" + encodeURIComponent(id) + "/decide", { method: "POST", json: { decision: "accept", note: n } }); },
  "appeal-reject": (id) => { const n = perguntar("Nota (pode ficar vazia):"); return n === null ? CANCELADO : api("/v1/admin/appeals/" + encodeURIComponent(id) + "/decide", { method: "POST", json: { decision: "reject", note: n } }); },
  "alert-resolve": (id) => { const n = perguntar("Nota (pode ficar vazia):"); return n === null ? CANCELADO : api("/v1/admin/safety-alerts/" + encodeURIComponent(id) + "/resolve", { method: "POST", json: { note: n } }); },
  "config-save": (chave) => {
    const campo = document.querySelector('textarea[data-chave="' + chave + '"]');
    let corpo;
    try { corpo = JSON.parse(campo.value); } catch (e) { throw new Error("O texto não é um JSON válido."); }
    return api("/v1/admin/config/" + encodeURIComponent(chave), { method: "PUT", json: corpo });
  },
};

async function aoClicar(evento) {
  const alvo = evento.target.closest("button[data-act]");
  if (!alvo) return;
  const { act, id, kind } = alvo.dataset;
  aviso("");
  try {
    if (act === "doc") return await abrirDocumento(id, kind);
    if (act === "ride-detail") {
      const d = await api("/v1/admin/rides/" + encodeURIComponent(id));
      el("detalhe").hidden = false; el("detalhe").textContent = JSON.stringify(d, null, 2);
      return;
    }
    const feito = await ACOES[act](id);
    if (feito === CANCELADO) return;
    aviso("Feito.", true);
    await mostrar(telaAtual);
  } catch (erro) { aviso(erro.message); }
}

function aoMudar(evento) {
  if (evento.target.id === "filtro-cadastros") { filtros.cadastros = evento.target.value; mostrar("cadastros"); }
  if (evento.target.id === "filtro-corridas") { filtros.corridas = evento.target.value; mostrar("corridas"); }
}

function iniciar() {
  el("entrada").hidden = true; el("menu").hidden = false; el("sair").hidden = false;
  el("menu").innerHTML = Object.entries(TELAS).map(([chave, nome]) => `<button data-tela="${attr(chave)}">${esc(nome)}</button>`).join("");
  mostrar(telaAtual);
}

function comecar() {
  document.addEventListener("click", aoClicar);
  document.addEventListener("change", aoMudar);
  el("sair").onclick = sair;
  el("menu").onclick = (e) => { const b = e.target.closest("button[data-tela]"); if (b) mostrar(b.dataset.tela); };
  el("tela").addEventListener("click", (e) => {
    if (e.target.id === "buscar-passageiros") { filtros.passageiros = el("busca-passageiros").value; mostrar("passageiros"); }
  });
  if (sessionStorage.getItem(TOKEN_KEY)) iniciar(); else mostrarEntrada();
}

if (typeof document !== "undefined") comecar();
if (typeof module !== "undefined") module.exports = { esc, attr, money, when, ACOES, CANCELADO };
