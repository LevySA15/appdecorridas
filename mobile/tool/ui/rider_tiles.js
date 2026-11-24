// Depuração: o mapa do app do motoqueiro baixa os ladrilhos?
const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const M = await h.phone(b, { url: 'http://127.0.0.1:8082/index.html', permissions: ['geolocation'] });
  const reqs = []; const falhas = [];
  M.page.on('request', (r) => { if (r.url().includes('tile.openstreetmap')) reqs.push(r.url()); });
  M.page.on('requestfailed', (r) => { if (r.url().includes('tile.openstreetmap')) falhas.push(r.url() + ' ' + (r.failure() || {}).errorText); });
  M.page.on('response', (r) => { if (r.url().includes('tile.openstreetmap') && r.status() >= 400) falhas.push(r.url() + ' ' + r.status()); });
  const RIDER = '759770' + String(Date.now()).slice(-5);
  const rider = await h.novoMotoqueiro(RIDER, Number(String(Date.now()).slice(-5)));
  await entrar(M.page, RIDER, null);
  await h.tap(M.page, 'Estou rodando');
  const pos = () => rider.call('POST', '/v1/rider/position', { lat: -12.9644, lng: -39.2597 });
  await pos(); const t = setInterval(pos, 3000);
  const pax = await h.pessoa('759996' + String(Date.now()).slice(-5), 'passenger');
  await pax.call('PUT', '/v1/me', { name: 'Teste Tiles' });
  const q = await pax.call('POST', '/v1/passenger/quotes', { pickup: { lat: -12.9644, lng: -39.2597, text: '' }, destination: { lat: -12.9600, lng: -39.2500, text: '' } });
  await pax.call('POST', '/v1/passenger/rides', { quote_id: q.quote_id, method: 'cash' });
  await M.page.waitForFunction(() => /Aceitar/.test(document.body.innerText + [...document.querySelectorAll('flt-semantics')].map((e) => e.textContent).join(' ')), null, { timeout: 30000 }).catch(() => {});
  await M.page.waitForTimeout(5000);
  console.log('pedidos de ladrilho:', reqs.length, 'falhas:', falhas.length, falhas.slice(0, 3));
  await h.shot(M.page, 'tiles-oferta');
  clearInterval(t);
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
