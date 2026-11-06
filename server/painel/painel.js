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
  cadastros: "Cadastros", corridas: "Corridas", passageiros: "Passageiros", dinheiro: "Dinheiro", saques: "Saques",
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
  pararAvisos();
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

// Textos puros (quem usa passa por esc()): ficam em funções para dar para testar sem abrir o painel.
function situacaoDoCadastro(r) {
  if (r.status === "pending" && r.resubmissions > 0) {
    return "pending · reenvio nº " + r.resubmissions + (r.previous_rejection ? " (recusado antes: " + r.previous_rejection + ")" : "");
  }
  return r.status + (r.reason ? ": " + r.reason : "");
}
function fotosDoCadastro(r) {
  return r.documents || [];   // fotos de cadastro recusado há mais de 30 dias são apagadas pelo servidor
}
function tipoDoAlerta(a) {
  if (a.kind === "sos" && a.raised_by === "rider") return "sos · pelo motoqueiro";
  if (a.kind === "sos" && a.raised_by === "passenger") return "sos · pelo passageiro";
  return a.kind + (a.suspected_mock ? " (localização suspeita)" : "");
}

// ---------- parâmetros (formulário) ----------
// Cada número ajustável do servidor, com nome em português. Tipos: cents (mostra reais, grava centavos), int, float,
// bool (sim/não) e json (só as faixas de taxa). Campo que o servidor tiver e não estiver aqui aparece com o nome cru;
// um teste do servidor falha para lembrar de dar nome a ele.
const PARAMETROS = {
  pricing: { titulo: "Preço da corrida", campos: {
    base_fare_cents: { rotulo: "Bandeirada (R$)", tipo: "cents" },
    per_km_cents: { rotulo: "Preço por quilômetro (R$)", tipo: "cents" },
    min_price_cents: { rotulo: "Preço mínimo da corrida (R$)", tipo: "cents" },
    round_to_cents: { rotulo: "Arredondar o preço para (R$)", tipo: "cents" },
    factor_min: { rotulo: "Fator de preço mínimo (1 = preço normal)", tipo: "float" },
    factor_max: { rotulo: "Fator de preço máximo", tipo: "float" },
    max_factor_step: { rotulo: "Quanto o fator pode mudar por atualização", tipo: "float" },
    factor_interval_s: { rotulo: "Tempo entre duas atualizações do fator (segundos)", tipo: "float" },
  } },
  fees: { titulo: "Taxa do app e entrada do motoqueiro", campos: {
    tiers: { rotulo: "Faixas da taxa por corrida do dia (JSON: from_ride, to_ride, fee_cents)", tipo: "json" },
    min_fee_cents: { rotulo: "Taxa mínima do app (R$)", tipo: "cents" },
    trial_rides: { rotulo: "Corridas de teste antes de pagar a entrada", tipo: "int" },
    entry_fee_cents: { rotulo: "Entrada do motoqueiro (R$, paga uma vez)", tipo: "cents" },
    cash_debt_limit_cents: { rotulo: "Dívida de taxa em dinheiro que bloqueia o motoqueiro (R$)", tipo: "cents" },
    max_debt_share: { rotulo: "Parte do ganho de uma corrida Pix que abate dívida (0,5 = metade)", tipo: "float" },
  } },
  rides: { titulo: "Corridas e cancelamento", campos: {
    pix_window_s: { rotulo: "Tempo para o passageiro pagar o Pix (segundos)", tipo: "int" },
    free_cancel_after_accept_s: { rotulo: "Cancelamento grátis depois que a moto aceita (segundos)", tipo: "int" },
    cancel_fee_min_cents: { rotulo: "Taxa de cancelamento tardio, mínima (R$)", tipo: "cents" },
    cancel_fee_max_cents: { rotulo: "Taxa de cancelamento tardio, máxima (R$)", tipo: "cents" },
    cancel_fee_round_cents: { rotulo: "Arredondar a taxa de cancelamento para (R$)", tipo: "cents" },
    cancel_fee_free_m: { rotulo: "Moto que andou menos que isso não gera taxa (metros)", tipo: "int" },
    cancel_fee_full_m: { rotulo: "Metros andados para a taxa chegar ao máximo", tipo: "int" },
    appeal_window_s: { rotulo: "Prazo para o passageiro pedir revisão da taxa (segundos)", tipo: "int" },
    max_wait_at_arrival_s: { rotulo: "Espera da moto no ponto de embarque (segundos)", tipo: "int" },
    queue_max_wait_s: { rotulo: "Espera máxima na fila da moto (segundos)", tipo: "int" },
    search_give_up_s: { rotulo: "Desistir de procurar moto depois de (segundos)", tipo: "int" },
    cash_pay_wait_s: { rotulo: "Espera pelo pagamento em dinheiro no fim da corrida (segundos)", tipo: "int" },
    quote_ttl_s: { rotulo: "Validade do preço mostrado ao passageiro (segundos)", tipo: "int" },
    min_trip_m: { rotulo: "Corrida mais curta (metros)", tipo: "int" },
    max_trip_m: { rotulo: "Corrida mais longa (metros, em linha reta)", tipo: "int" },
  } },
  dispatch: { titulo: "Busca de moto", campos: {
    offer_timeout_s: { rotulo: "Tempo que a moto tem para aceitar a oferta (segundos)", tipo: "int" },
    max_candidates_routed: { rotulo: "Quantas motos entram na comparação do trajeto", tipo: "int" },
    finishing_max_s: { rotulo: "Moto terminando uma corrida: no máximo (segundos)", tipo: "int" },
    finishing_max_m: { rotulo: "Moto terminando uma corrida: no máximo (metros)", tipo: "int" },
    search_radius_m: { rotulo: "Raio da busca de motos (metros)", tipo: "float" },
    position_max_age_s: { rotulo: "Posição mais velha que isso não conta (segundos)", tipo: "float" },
  } },
  safety: { titulo: "Segurança", campos: {
    stopped_after_s: { rotulo: "Moto parada: avisar depois de (segundos)", tipo: "int" },
    stopped_radius_m: { rotulo: "Moto parada: dentro de um raio de (metros)", tipo: "float" },
    off_route_m: { rotulo: "Fora da rota: distância da rota (metros)", tipo: "float" },
    off_route_confirmations: { rotulo: "Fora da rota: confirmações antes de avisar", tipo: "int" },
    max_plausible_speed_kmh: { rotulo: "Velocidade máxima que faz sentido (km/h)", tipo: "float" },
    reanchor_after_rejects: { rotulo: "Posições recusadas seguidas até recomeçar a conta", tipo: "int" },
    mock_location_jumps: { rotulo: "Saltos de posição até suspeitar de localização falsa", tipo: "int" },
    alert_cooldown_s: { rotulo: "Espera antes de repetir o mesmo tipo de aviso (segundos)", tipo: "int" },
    no_signal_short_m: { rotulo: "Sem sinal: corrida curta vai até (metros)", tipo: "int" },
    no_signal_long_m: { rotulo: "Sem sinal: corrida média vai até (metros)", tipo: "int" },
    no_signal_short_s: { rotulo: "Sem sinal em corrida curta: avisar depois de (segundos)", tipo: "int" },
    no_signal_mid_s: { rotulo: "Sem sinal em corrida média: avisar depois de (segundos)", tipo: "int" },
    no_signal_long_s: { rotulo: "Sem sinal em corrida longa: avisar depois de (segundos)", tipo: "int" },
    max_samples: { rotulo: "Posições guardadas por corrida", tipo: "int" },
  } },
  auth: { titulo: "Login", campos: {
    otp_digits: { rotulo: "Dígitos do código de login", tipo: "int" },
    otp_ttl_s: { rotulo: "Validade do código de login (segundos)", tipo: "int" },
    otp_max_attempts: { rotulo: "Tentativas de código antes de travar", tipo: "int" },
    otp_requests_per_hour: { rotulo: "Pedidos de código por número, por hora", tipo: "int" },
    otp_requests_per_ip_hour: { rotulo: "Pedidos de código por aparelho/rede, por hora", tipo: "int" },
    session_days: { rotulo: "Dias que o login dura", tipo: "int" },
  } },
  balance: { titulo: "Saldo do passageiro", campos: {
    topup_enabled: { rotulo: "Recarga de saldo ligada", tipo: "bool" },
    topup_min_cents: { rotulo: "Recarga mínima (R$)", tipo: "cents" },
    topup_max_cents: { rotulo: "Recarga máxima (R$)", tipo: "cents" },
    pay_rides_enabled: { rotulo: "O saldo paga a corrida", tipo: "bool" },
    withdraw_enabled: { rotulo: "Saque do saldo por Pix ligado", tipo: "bool" },
    withdraw_min_cents: { rotulo: "Saque mínimo (R$)", tipo: "cents" },
    withdraw_max_cents: { rotulo: "Saque máximo (R$)", tipo: "cents" },
  } },
};

// O que o servidor mandou -> texto do campo. Dinheiro aparece em reais, com vírgula.
function paraCampo(tipo, valor) {
  if (tipo === "cents") return (Number(valor) / 100).toFixed(2).replace(".", ",");
  if (tipo === "bool") return valor ? "sim" : "nao";
  if (tipo === "json") return JSON.stringify(valor, null, 2);
  return String(valor).replace(".", ",");
}

// Texto do campo -> o que o servidor espera. Erro já vem com o nome do campo.
function doCampo(tipo, texto, rotulo) {
  const limpo = String(texto).trim();
  if (tipo === "bool") return limpo === "sim";
  if (tipo === "json") {
    try { return JSON.parse(limpo); } catch (erro) { throw new Error(rotulo + ": o texto não é um JSON válido."); }
  }
  const numero = limpo === "" ? NaN : Number(limpo.replace(",", "."));
  if (!Number.isFinite(numero)) throw new Error(rotulo + ": informe um número.");
  if (tipo === "cents") return Math.round(numero * 100);
  if (tipo === "int" && !Number.isInteger(numero)) throw new Error(rotulo + ": use um número inteiro, sem vírgula.");
  return numero;
}

function coletarBloco(campos) {
  const corpo = {};
  for (const c of campos) corpo[c.campo] = doCampo(c.tipo, c.texto, c.rotulo);
  return corpo;
}

// ---------- telas ----------
const VISOES = {
  async cadastros() {
    const estado = filtros.cadastros;
    const lista = await api("/v1/admin/riders?status=" + encodeURIComponent(estado) + "&limit=100");
    const opcoes = ["pending", "approved", "blocked", "rejected"].map((s) => `<option value="${attr(s)}" ${raw(s === estado ? "selected" : "")}>${esc(s)}</option>`).join("");
    const linhas = lista.map((r) => [
      esc(r.name), esc(r.phone), esc(r.plate + " · " + r.moto_model), esc(situacaoDoCadastro(r)),
      esc((r.cnh_expires_on || "–") + " / " + (r.crlv_expires_on || "–")),
      raw(fotosDoCadastro(r).map((k) => botao("doc", r.rider_id, k, "", `data-kind="${attr(k)}"`)).join(" ")),
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
  async saques() {
    const lista = await api("/v1/admin/withdrawals?limit=100");
    return tabela(["Quando", "Passageiro", "Valor", "Chave"], lista.map((s) => [
      esc(when(s.created_at)), esc(s.passenger_name), esc(money(s.amount_cents)), esc(s.key_kind + " " + s.key_masked),
    ]));
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
      esc(when(a.created_at)), esc(tipoDoAlerta(a)), esc(a.status), esc(a.passenger_name),
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

// ---------- avisos ao vivo (WebSocket do mesmo endereço; o servidor manda aos administradores o que importa) ----------
const TITULO = "Painel do dono";
const ESPERA_RECONEXAO_MS = 3000;
const CODIGO_SESSAO_ACABOU = 4401;
let ligacao = null;
let avisosNovos = 0;
let telaDoAviso = "alertas";
let textoDaCaixa = "";
let urgenteNaCaixa = false;     // um SOS na caixa não é apagado por um aviso comum que chegue depois

function descreverAviso(mensagem) {
  const dados = (mensagem && mensagem.data) || {};
  switch (mensagem && mensagem.type) {
    case "sos": {
      const quem = { rider: " pelo motoqueiro", passenger: " pelo passageiro" }[dados.raised_by] || "";
      return { texto: "SOS" + quem, tela: "alertas", urgente: true };
    }
    case "safety_alert":
      return { texto: "Alerta de segurança: " + ({ stopped: "parou", off_route: "saiu da rota", no_signal: "sem sinal" }[dados.kind] || "atenção"), tela: "alertas", urgente: false };
    case "mock_location_suspected":
      return { texto: "Localização suspeita numa corrida", tela: "alertas", urgente: false };
    case "appeal_opened":
      return { texto: "Novo recurso de taxa de cancelamento", tela: "recursos", urgente: false };
    default:
      return null;
  }
}

// Mantém uma conexão aberta: manda o token ao abrir, refaz sozinha se cair e para quando mandam (`fechar`) ou quando o
// servidor diz que a sessão acabou. Nunca há duas conexões vivas ao mesmo tempo.
function conectarAvisos({ criarSocket, agendar, cancelar, token, aoMensagem, aoRecusar }) {
  let fechado = false;
  let socket = null;
  let pendente = null;
  function abrir() {
    pendente = null;
    if (fechado) return;
    const este = criarSocket();
    socket = este;
    este.onopen = () => este.send(JSON.stringify({ token }));
    este.onmessage = (evento) => { try { aoMensagem(JSON.parse(evento.data)); } catch (erro) { /* mensagem ruim: ignora */ } };
    este.onclose = (evento) => {
      if (fechado || socket !== este) return;
      socket = null;
      if (evento && evento.code === CODIGO_SESSAO_ACABOU) { fechado = true; if (aoRecusar) aoRecusar(); return; }
      pendente = agendar(abrir, ESPERA_RECONEXAO_MS);
    };
  }
  abrir();
  return {
    fechar() {
      fechado = true;
      if (pendente !== null && cancelar) cancelar(pendente);
      pendente = null;
      const aberto = socket;
      socket = null;
      if (aberto) aberto.close();
    },
  };
}

function limparAviso() {
  avisosNovos = 0;
  urgenteNaCaixa = false;
  el("alerta-vivo").hidden = true;
  document.title = TITULO;
}

function aoAviso(mensagem) {
  const aviso = descreverAviso(mensagem);
  if (!aviso) {
    if (mensagem && mensagem.type === "safety_ok" && telaAtual === "alertas") mostrar("alertas");   // o passageiro respondeu "tudo bem"
    return;
  }
  avisosNovos += 1;
  const manterTexto = urgenteNaCaixa && !aviso.urgente;           // fica o texto do SOS; só a contagem sobe
  if (!manterTexto) { urgenteNaCaixa = aviso.urgente; telaDoAviso = aviso.tela; textoDaCaixa = aviso.texto; }
  const caixa = el("alerta-vivo");
  caixa.textContent = textoDaCaixa + (avisosNovos > 1 ? " (+" + (avisosNovos - 1) + ")" : "") + " — clique para ver";   // textContent: nunca HTML
  caixa.className = urgenteNaCaixa ? "urgente" : "";
  caixa.hidden = false;
  document.title = "(!) " + textoDaCaixa + " — " + TITULO;
  if (telaAtual === aviso.tela) mostrar(aviso.tela);
}

function pararAvisos() {
  if (ligacao) { ligacao.fechar(); ligacao = null; }
  limparAviso();
}

function comecarAvisos() {
  pararAvisos();
  const endereco = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/v1/ws";
  ligacao = conectarAvisos({
    criarSocket: () => new WebSocket(endereco), agendar: (fn, ms) => setTimeout(fn, ms), cancelar: (id) => clearTimeout(id),
    token: sessionStorage.getItem(TOKEN_KEY), aoMensagem: aoAviso, aoRecusar: sair,
  });
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
  comecarAvisos();
}

function comecar() {
  document.addEventListener("click", aoClicar);
  document.addEventListener("change", aoMudar);
  el("sair").onclick = sair;
  el("alerta-vivo").onclick = () => { const tela = telaDoAviso; limparAviso(); mostrar(tela); };
  el("menu").onclick = (e) => { const b = e.target.closest("button[data-tela]"); if (b) mostrar(b.dataset.tela); };
  el("tela").addEventListener("click", (e) => {
    if (e.target.id === "buscar-passageiros") { filtros.passageiros = el("busca-passageiros").value; mostrar("passageiros"); }
  });
  if (sessionStorage.getItem(TOKEN_KEY)) iniciar(); else mostrarEntrada();
}

if (typeof document !== "undefined") comecar();
if (typeof module !== "undefined") module.exports = { esc, attr, money, when, ACOES, CANCELADO, TELAS, VISOES, PARAMETROS, paraCampo, doCampo, coletarBloco, mostrar, descreverAviso, conectarAvisos, aoAviso, limparAviso, situacaoDoCadastro, tipoDoAlerta, fotosDoCadastro };
