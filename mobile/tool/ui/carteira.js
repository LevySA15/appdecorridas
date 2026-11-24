// Carteira do passageiro: recarregar por Pix, pagar, sacar. Mostra os diálogos.
const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const PAX = process.env.PAX || ('759999' + String(Date.now()).slice(-5));
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const log = (m) => console.log(m);
  const snap = async (name) => { const t = await h.text(P.page); log(`--- ${name}: ${t}`); await h.shot(P.page, `w-${tag}-${name}`); return t; };
  const adm = await h.admin();
  // liga recarga e saque no servidor descartável (vêm desligados até a resposta do advogado)
  const cfg = await adm.call('GET', '/v1/admin/config');
  log('config balance: ' + JSON.stringify(cfg.balance || cfg).slice(0, 300));
  await entrar(P.page, PAX, 'Carla Carteira');
  await h.tap(P.page, 'Carteira');
  await P.page.waitForTimeout(1500);
  await snap('01-carteira');
  await h.tap(P.page, 'Recarregar').catch((e) => log('sem Recarregar: ' + e.message.split('\n')[0]));
  await P.page.waitForTimeout(1000);
  await snap('02-dialogo-recarga');
  console.log('erros:', P.logs.join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
