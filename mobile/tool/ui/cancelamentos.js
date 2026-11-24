// Cancelamentos, sem moto, SOS e "está tudo bem?" pela tela do passageiro; o motoqueiro age pela API (mais rápido).
const h = require('./harness');
const { entrar } = require('./fluxo');
const PAX = process.env.PAX || '75999990021';
const RIDER = process.env.RIDER || ('759770' + String(Date.now()).slice(-5));
const waitText = (page, re, ms = 30000) => page.waitForFunction((src) => {
  const t = [...document.querySelectorAll('flt-semantics')].filter((e) => !e.querySelector('flt-semantics')).map((e) => e.getAttribute('aria-label') || e.textContent || '').join(' | ');
  return new RegExp(src).test(t);
}, re.source, { timeout: ms });

(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const rider = await h.novoMotoqueiro(RIDER, Number(String(Date.now()).slice(-5)));
  const adm = await h.admin();
  const log = (m) => console.log(m);
  const snap = async (name) => { const t = await h.text(P.page); log(`--- ${name}: ${t}`); await h.shot(P.page, `c-${tag}-${name}`); return t; };
  const pedir = async (metodo = 'Dinheiro') => {
    await h.tap(P.page, 'Pedir corrida', { exact: true });
    await P.page.waitForTimeout(1200);
    await h.tapAt(P.page, 150, 330);
    await h.tapAt(P.page, 260, 450);
    await waitText(P.page, /Pedir corrida/);
    await h.tap(P.page, metodo);
    await h.tap(P.page, 'Pedir corrida', { exact: true });
    await P.page.waitForTimeout(2000);
  };
  const quitarDivida = async () => {
    const st = await rider.call('GET', '/v1/rider/state');
    if (st.account && st.account.blocked_reason === 'debt_pending') {
      const c = await rider.call('POST', '/v1/rider/debt-charge', {});
      await fetch(`${h.API}/v1/dev/pix/${c.charge_id}/pay`, { method: 'POST' });
      log('dívida do motoqueiro quitada');
    }
  };
  let batida = null;   // o app manda a posição a cada ~4 s; sem isso o servidor acha que a moto sumiu
  const motoOnline = async (on) => {
    if (batida) { clearInterval(batida); batida = null; }
    if (on) {
      batida = setInterval(() => rider.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 }).catch(() => {}), 3000);
      await quitarDivida();
      await rider.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 });
      const r = await rider.call('POST', '/v1/rider/online');
      if (r) log('online devolveu: ' + JSON.stringify(r).slice(0, 200));
    }
    else await rider.call('POST', '/v1/rider/offline');
  };
  const aceitar = async () => {
    for (let i = 0; i < 30; i++) {
      const st = await rider.call('GET', '/v1/rider/state');
      if (st.offer) { await rider.call('POST', `/v1/rider/offers/${st.offer.ride_id}/accept`); return st.offer.ride_id; }
      await new Promise((r) => setTimeout(r, 1000));
    }
    throw new Error('a oferta não chegou ao motoqueiro');
  };

  await entrar(P.page, PAX, 'Ana Cancela');

  // 1) cancelar enquanto procura (sem nenhuma moto)
  await motoOnline(false);
  await pedir();
  await snap('01-procurando-sem-moto');
  await h.tap(P.page, 'Cancelar');
  await P.page.waitForTimeout(1500);
  await snap('02-cancelou-procurando');

  // 2) moto aceita e o passageiro cancela dentro da janela grátis
  await motoOnline(true);
  await pedir();
  const ride2 = await aceitar();
  await P.page.waitForTimeout(2500);
  await snap('03-moto-a-caminho');
  await h.tap(P.page, 'Cancelar');
  await P.page.waitForTimeout(2000);
  await snap('04-cancelou-com-moto');

  // 3) SOS durante a corrida
  await pedir();
  const ride3 = await aceitar();
  await P.page.waitForTimeout(2500);
  await h.tap(P.page, 'SOS');
  await P.page.waitForTimeout(2000);
  await snap('05-sos');
  const alertas = await adm.call('GET', '/v1/admin/safety-alerts?status=open&limit=10');
  log('alertas abertos no servidor: ' + JSON.stringify(alertas).slice(0, 300));
  await rider.call('POST', `/v1/rider/rides/${ride3}/arrive`).catch(() => {});
  await h.tap(P.page, 'Cancelar').catch(() => {});
  await P.page.waitForTimeout(2000);
  await snap('06-depois-do-sos');
  log('erros: ' + P.logs.join(' || '));
  if (batida) clearInterval(batida);
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
