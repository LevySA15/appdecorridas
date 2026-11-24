// As telas secundárias do passageiro (carteira, histórico, recibo, perfil) num passageiro que já tem corridas.
const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const snap = async (name) => { const t = await h.text(P.page); console.log(`--- ${name}: ${t}`); await h.shot(P.page, `p2-${tag}-${name}`); return t; };
  await entrar(P.page, process.env.PAX || '75999990009', 'Maria Teste');
  await h.tap(P.page, 'Carteira');
  await P.page.waitForTimeout(1500);
  await snap('01-carteira');
  await h.tap(P.page, 'Voltar');
  await P.page.waitForTimeout(800);
  await h.tap(P.page, 'Minhas corridas');
  await P.page.waitForTimeout(2000);
  const t = await snap('02-historico');
  const primeira = P.page.locator('flt-semantics[role=button], flt-semantics[flt-tappable]').filter({ hasText: /R\$/ }).first();
  if (await primeira.count()) { await primeira.click({ force: true }); await P.page.waitForTimeout(1500); await snap('03-recibo'); await h.tap(P.page, 'Voltar'); await P.page.waitForTimeout(600); }
  await h.tap(P.page, 'Voltar');
  await P.page.waitForTimeout(600);
  await h.tap(P.page, 'Perfil');
  await P.page.waitForTimeout(1500);
  await snap('04-perfil');
  console.log('erros:', P.logs.join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
