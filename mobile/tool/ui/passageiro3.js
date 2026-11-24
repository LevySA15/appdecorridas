const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const { page, logs } = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  const say = async (n) => { console.log(`--- ${n}`); console.log(await h.text(page)); await h.shot(page, `p-${tag}-${n}`); };
  await entrar(page, '75999990001', 'Maria Teste');
  await h.tap(page, 'Pedir corrida', { exact: true });
  await page.waitForTimeout(1500);
  await say('04-nova-corrida');
  // marca origem e destino no mapa de mentira
  await h.tapAt(page, 150, 330); await page.waitForTimeout(500);
  await say('05-origem-marcada');
  await h.tapAt(page, 260, 450); await page.waitForTimeout(2500);
  await say('06-cotacao');
  console.log(logs.join('\n'));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
