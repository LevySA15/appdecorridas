// Internet caindo: pedir sem conexão, abrir o app sem conseguir falar com o servidor, perder a conexão no meio da corrida.
const h = require('./harness');
const { entrar } = require('./fluxo');
const PAX = process.env.PAX || '75999990031';
const waitText = (page, re, ms = 30000) => page.waitForFunction((src) => {
  const t = [...document.querySelectorAll('flt-semantics')].filter((e) => !e.querySelector('flt-semantics')).map((e) => e.getAttribute('aria-label') || e.textContent || '').join(' | ');
  return new RegExp(src).test(t);
}, re.source, { timeout: ms });

(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const log = (m) => console.log(m);
  const snap = async (name) => { const t = await h.text(P.page); log(`--- ${name}: ${t}`); await h.shot(P.page, `o-${tag}-${name}`); return t; };
  await entrar(P.page, PAX, 'Ana Offline');

  // 1) sem internet na hora de pedir
  await P.ctx.setOffline(true);
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(1200);
  await h.tapAt(P.page, 150, 330);
  await h.tapAt(P.page, 260, 450);
  await P.page.waitForTimeout(2500);
  await snap('01-pedir-sem-internet');
  await P.ctx.setOffline(false);
  // o toque seguinte marca de novo
  await h.tapAt(P.page, 150, 330);
  await h.tapAt(P.page, 260, 450);
  await P.page.waitForTimeout(2500);
  await snap('02-pedir-com-internet-de-novo');
  await h.tap(P.page, 'Voltar');
  await P.page.waitForTimeout(800);

  // 2) abrir o app com o servidor fora do ar (a página carrega, a API não)
  await P.ctx.route('**/v1/**', (r) => r.abort());
  await P.page.reload();
  await P.page.waitForSelector('flt-semantics-placeholder', { state: 'attached', timeout: 60000 });
  await P.page.evaluate(() => document.querySelector('flt-semantics-placeholder')?.click());
  await P.page.waitForTimeout(3500);
  await snap('03-abrir-sem-servidor');
  await P.ctx.unroute('**/v1/**');
  await h.tap(P.page, 'Tentar de novo').catch((e) => log('sem botão tentar de novo: ' + e.message.split('\n')[0]));
  await P.page.waitForTimeout(2500);
  await snap('04-voltou');
  log('erros: ' + P.logs.join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
