const h = require('./harness');
const { entrar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const { page, logs } = await h.phone(b, { dark, url: 'http://127.0.0.1:8081/index.html' });
  await entrar(page, '75999990001', 'Maria Teste');
  await h.tap(page, 'Pedir corrida', { exact: true });
  await page.waitForTimeout(1200);
  await h.tapAt(page, 150, 330);
  await h.tapAt(page, 260, 450);
  await page.waitForTimeout(3000);
  console.log(await h.text(page));
  await h.tap(page, 'Dinheiro');
  await h.tap(page, 'Pedir corrida', { exact: true });
  let last = '', n = 0;
  for (let i = 0; i < 70; i++) {
    await page.waitForTimeout(3000);
    const t = await h.text(page);
    if (t !== last) { n++; last = t; console.log(`--- t=${(i + 1) * 3}s estado ${n}\n${t}`); await h.shot(page, `p-${tag}-10-corrida-${String(n).padStart(2, '0')}`); }
    if (/Avaliar|Como foi/.test(t)) break;
  }
  console.log(logs.join('\n'));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
