const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const reqs = []; const t0 = Date.now(); P.page.on('request', (r) => { if (r.url().includes('tile.openstreetmap')) reqs.push(((Date.now() - t0) / 1000).toFixed(1) + 's ' + r.url().replace('https://tile.openstreetmap.org/', '')); });
  await entrar(P.page, '759997' + String(Date.now()).slice(-5), 'Maria Mapa');
  await P.page.waitForTimeout(4000);
  await h.shot(P.page, `osm-${dark ? 'escuro' : 'claro'}-inicio`);
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(4000);
  await h.shot(P.page, `osm-${dark ? 'escuro' : 'claro'}-pedir`);
  console.log(await h.text(P.page)); console.log('pedidos:', reqs.length, reqs.slice(0, 5).join(' | '), '...', reqs.slice(-3).join(' | '));
  console.log('erros:', P.logs.slice(0, 8).join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
