// A internet do passageiro cai no meio da corrida e o motoqueiro age nesse intervalo: ao voltar, a tela tem de se acertar sozinha.
const h = require('./harness');
const { entrar } = require('./fluxo');
const PAX = process.env.PAX || '75999990041';
const RIDER = '759770' + String(Date.now()).slice(-5);
const waitText = (page, re, ms = 30000) => page.waitForFunction((src) => {
  const t = [...document.querySelectorAll('flt-semantics')].filter((e) => !e.querySelector('flt-semantics')).map((e) => e.getAttribute('aria-label') || e.textContent || '').join(' | ');
  return new RegExp(src).test(t);
}, re.source, { timeout: ms });

(async () => {
  const b = await h.browser();
  const P = await h.phone(b, { url: 'http://127.0.0.1:8081/index.html' });
  const rider = await h.novoMotoqueiro(RIDER, Number(String(Date.now()).slice(-5)));
  const log = (m) => console.log(m);
  const snap = async (name) => { const t = await h.text(P.page); log(`--- ${name}: ${t}`); await h.shot(P.page, `r-${name}`); return t; };
  const batida = setInterval(() => rider.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 }).catch(() => {}), 3000);
  await rider.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 });
  await rider.call('POST', '/v1/rider/online');
  await entrar(P.page, PAX, 'Ana Reconecta');
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(1200);
  await h.tapAt(P.page, 150, 330); await h.tapAt(P.page, 260, 450);
  await waitText(P.page, /Pedir corrida/);
  await h.tap(P.page, 'Dinheiro');
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  let ride = null;
  for (let i = 0; i < 30 && !ride; i++) { const st = await rider.call('GET', '/v1/rider/state'); if (st.offer) ride = st.offer.ride_id; else await new Promise((r) => setTimeout(r, 1000)); }
  await rider.call('POST', `/v1/rider/offers/${ride}/accept`);
  await waitText(P.page, /a caminho/);
  await snap('01-a-caminho');

  await P.ctx.setOffline(true);
  await P.page.waitForTimeout(3000);
  await rider.call('POST', `/v1/rider/rides/${ride}/arrive`);   // acontece enquanto o passageiro está sem internet
  await P.page.waitForTimeout(4000);
  await snap('02-sem-internet');
  await P.ctx.setOffline(false);
  const t0 = Date.now();
  await waitText(P.page, /Sua moto chegou/, 45000);
  log(`reconectou e atualizou em ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  await snap('03-voltou-e-atualizou');
  await h.tap(P.page, 'Cancelar').catch(() => {});
  clearInterval(batida);
  log('erros: ' + P.logs.join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
