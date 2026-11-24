// Percorre os dois apps de ponta a ponta (uma corrida em Pix) e as telas secundárias, e grava uma foto de cada tela.
// node galeria.js claro|escuro   (SHOTS=<pasta> SHOT_JPEG=1)
const h = require('./harness');
const { entrar } = require('./fluxo');
const path = require('path');
const FOTO = path.join(__dirname, 'foto-teste.png');
const APP_P = 'http://127.0.0.1:8081/index.html';
const APP_M = 'http://127.0.0.1:8082/index.html';
const waitText = (page, re, ms = 30000) => page.waitForFunction((src) => {
  const t = [...document.querySelectorAll('flt-semantics')].filter((e) => !e.querySelector('flt-semantics')).map((e) => e.getAttribute('aria-label') || e.textContent || '').join(' | ');
  return new RegExp(src).test(t);
}, re.source, { timeout: ms });

const achou0 = (lista) => Array.isArray(lista) && lista.length > 0;
(async () => {
  const b = await h.browser();
  // o servidor de teste dá só 8 s para aceitar; a galeria precisa de tempo para fotografar a oferta
  { const a = await h.admin(); const c = await a.call('GET', '/v1/admin/config'); const r = await a.call('PUT', '/v1/admin/config/dispatch', { ...c.dispatch, offer_timeout_s: 60 }); if (r && r.error) console.log('config: ' + JSON.stringify(r)); }
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const sufixo = String(Date.now()).slice(-5);
  const PAX = '759998' + sufixo;
  const RIDER = '759775' + sufixo;
  const log = (m) => console.log(m);
  // os ladrilhos do mapa chegam da internet: espera antes de cada foto
  const foto = async (ctx, who, name) => { await ctx.page.waitForTimeout(2600); await h.shot(ctx.page, `${who}-${tag}-${name}`); };

  // ---------- passageiro: entrar ----------
  const P = await h.phone(b, { dark, url: APP_P, permissions: ['geolocation'] });
  await P.page.waitForTimeout(1200);
  await foto(P, 'p', '01-entrar');
  await h.type(P.page, 'Telefone', PAX);
  await h.tap(P.page, 'Enviar código');
  await P.page.waitForTimeout(900);
  await h.type(P.page, 'Código', await h.otp(PAX));
  await foto(P, 'p', '02-codigo');
  await h.tap(P.page, 'Entrar', { exact: true });
  await P.page.waitForTimeout(2000);
  await foto(P, 'p', '03-nome');
  await h.type(P.page, 'Seu nome', 'Maria Teixeira');
  await h.tap(P.page, 'Continuar');
  await P.page.waitForTimeout(2300);
  await foto(P, 'p', '04-inicio');

  // ---------- motoqueiro: cadastro, espera e aprovação ----------
  const M = await h.phone(b, { dark, url: APP_M });
  await M.page.waitForTimeout(1200);
  await foto(M, 'm', '01-entrar');
  await h.type(M.page, 'Telefone', RIDER);
  await h.tap(M.page, 'Enviar código');
  await M.page.waitForTimeout(900);
  await h.type(M.page, 'Código', await h.otp(RIDER));
  await h.tap(M.page, 'Entrar', { exact: true });
  await M.page.waitForTimeout(2500);
  await h.type(M.page, 'Nome completo', 'João Batista Souza');
  const n = Number(sufixo);
  await h.type(M.page, 'CPF', h.cpfValido(n));
  await h.type(M.page, 'Número da CNH', String(30000000000 + n));
  await h.type(M.page, 'Placa da moto', `RTA${n % 10}B${String(10 + (n % 90))}`);
  await h.type(M.page, 'Modelo da moto', 'Honda CG 160 Fan');
  await h.type(M.page, 'Validade da CNH', '31122030');
  await h.type(M.page, 'Validade do documento da moto', '31122030');
  await foto(M, 'm', '02-cadastro');
  for (let i = 0; i < 3; i++) {
    const [chooser] = await Promise.all([M.page.waitForEvent('filechooser', { timeout: 8000 }), h.tap(M.page, 'Tirar foto', { nth: 0 })]);
    await chooser.setFiles(FOTO);
    await M.page.waitForTimeout(700);
  }
  await h.tap(M.page, 'Enviar cadastro');
  await M.page.waitForTimeout(3200);
  await foto(M, 'm', '03-em-analise');
  const adm = await h.admin();
  const lista = await adm.call('GET', '/v1/admin/riders?status=pending&limit=200');
  if (!achou0(lista)) { log('texto do app: ' + await h.text(M.page)); log('lista: ' + JSON.stringify(lista).slice(0, 300)); }
  const achou = lista.find((r) => String(r.phone).endsWith(RIDER.slice(-8)));
  await adm.call('POST', `/v1/admin/riders/${achou.rider_id}/approve`, {});
  await M.page.waitForTimeout(3500);
  if ((await h.text(M.page)).includes('Atualizar')) { await h.tap(M.page, 'Atualizar'); await M.page.waitForTimeout(2500); }
  await foto(M, 'm', '04-inicio-parado');
  await h.tap(M.page, 'Estou rodando');
  await M.page.waitForTimeout(2500);
  await foto(M, 'm', '05-inicio-rodando');
  const riderApi = await h.pessoa(RIDER, 'rider');
  const batida = setInterval(() => riderApi.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 }).catch(() => {}), 3000);

  // ---------- passageiro pede (Pix) ----------
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(1500);
  await P.page.waitForTimeout(2500);   // os ladrilhos do mapa chegam da internet
  await foto(P, 'p', '05-marcar-no-mapa');
  await h.tap(P.page, 'Estou aqui');
  await P.page.waitForTimeout(2500);
  await foto(P, 'p', '05b-estou-aqui');
  await h.tapAt(P.page, 330, 600);
  await waitText(P.page, /Pedir corrida/);
  await P.page.waitForTimeout(2500);
  await foto(P, 'p', '06-cotacao');
  await h.tap(P.page, 'Pix');
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(2000);
  await foto(P, 'p', '07-procurando');
  await waitText(M.page, /Aceitar/, 40000);
  await foto(M, 'm', '06-oferta');
  await h.tap(M.page, 'Aceitar');
  await M.page.waitForTimeout(2500);
  await foto(M, 'm', '07-a-caminho');
  await foto(P, 'p', '08-moto-a-caminho');
  const paxApi = await h.pessoa(PAX, 'passenger');
  let st = await paxApi.call('GET', '/v1/passenger/state');
  for (let i = 0; i < 12 && !(st.ride && st.ride.pay); i++) { await new Promise((r) => setTimeout(r, 1000)); st = await paxApi.call('GET', '/v1/passenger/state'); }
  if (!(st.ride && st.ride.pay)) throw new Error('o Pix da corrida não apareceu: ' + JSON.stringify(st.ride).slice(0, 300));
  const chargeId = st.ride.pay.charge_id;
  await h.tap(P.page, 'Ver Pix');
  await P.page.waitForTimeout(1500);
  await foto(P, 'p', '09-pix');
  await fetch(`${h.API}/v1/dev/pix/${chargeId}/pay`, { method: 'POST' });
  await h.tap(P.page, 'Fechar');
  await P.page.waitForTimeout(1200);
  await h.tap(M.page, 'Ir até o ponto de embarque').catch(() => {});
  await h.tap(M.page, 'Cheguei', { exact: true });
  await M.page.waitForTimeout(2500);
  await foto(M, 'm', '08-cheguei-pedir-codigo');
  await foto(P, 'p', '10-moto-chegou');
  const pin = ((await h.text(P.page)).match(/\b(\d{4})\b/) || [])[1];
  await h.tap(M.page, 'Confirmei o capacete extra');
  await M.page.waitForTimeout(1200);
  await h.type(M.page, 'Código do passageiro', pin);
  await h.tap(M.page, 'Começar corrida');
  await M.page.waitForTimeout(2500);
  await foto(M, 'm', '09-em-viagem');
  await foto(P, 'p', '11-em-viagem');
  await h.tap(M.page, 'Ir até o destino').catch(() => {});
  await h.tap(M.page, 'Finalizar corrida');
  await M.page.waitForTimeout(3000);
  await foto(M, 'm', '10-avaliar');
  await foto(P, 'p', '12-avaliar');
  await h.tap(P.page, '5 estrelas');
  await h.tap(M.page, '5 estrelas');
  await P.page.waitForTimeout(2000);
  await h.tap(M.page, 'Extrato do dia');
  await M.page.waitForTimeout(2000);
  await foto(M, 'm', '11-extrato');
  clearInterval(batida);

  // ---------- passageiro: telas secundárias ----------
  await h.tap(P.page, 'Carteira');
  await P.page.waitForTimeout(1500);
  await foto(P, 'p', '13-carteira');
  await h.tap(P.page, 'Recarregar');
  await P.page.waitForTimeout(900);
  await foto(P, 'p', '14-recarga');
  await P.page.keyboard.press('Escape');
  await h.tap(P.page, 'Cancelar').catch(() => {});
  await P.page.waitForTimeout(600);
  await h.tap(P.page, 'Voltar');
  await P.page.waitForTimeout(800);
  await h.tap(P.page, 'Minhas corridas');
  await P.page.waitForTimeout(1800);
  await foto(P, 'p', '15-historico');
  const corrida = P.page.locator('flt-semantics[role=button], flt-semantics[flt-tappable]').filter({ hasText: /R\$/ }).first();
  if (await corrida.count()) { await corrida.click({ force: true }); await P.page.waitForTimeout(1500); await foto(P, 'p', '16-recibo'); await h.tap(P.page, 'Voltar'); await P.page.waitForTimeout(600); }
  await h.tap(P.page, 'Voltar');
  await P.page.waitForTimeout(600);
  await h.tap(P.page, 'Perfil');
  await P.page.waitForTimeout(1500);
  await foto(P, 'p', '17-perfil');
  log('galeria ' + tag + ' pronta. erros: ' + [...P.logs, ...M.logs].join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
