// Entra no painel do dono (administrador do servidor descartável) e fotografa cada aba.
const h = require('./harness');
const { chromium } = require('playwright-core');
(async () => {
  const b = await h.browser();
  const largura = Number(process.argv[2] || 1280);
  const ctx = await b.newContext({ viewport: { width: largura, height: 900 }, colorScheme: process.argv[3] === 'escuro' ? 'dark' : 'light', locale: 'pt-BR' });
  const page = await ctx.newPage();
  const erros = [];
  page.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
  page.on('pageerror', (e) => erros.push('pageerror ' + e.message));
  await page.goto(`${h.API}/painel/`);
  await page.fill('#telefone', '75 99999-0000');
  await page.click('#pedir-codigo');
  await page.waitForSelector('#pegar-codigo:visible');
  await page.click('#pegar-codigo');
  await page.click('#entrar');
  await page.waitForSelector('#menu button');
  const abas = await page.$$eval('#menu button', (bs) => bs.map((x) => x.dataset.tela));
  const tag = `${largura}${process.argv[3] === 'escuro' ? 'e' : ''}`;
  for (const aba of abas) {
    await page.click(`#menu button[data-tela="${aba}"]`);
    await page.waitForTimeout(900);
    await h.shot(page, `painel-${tag}-${aba}`);
  }
  console.log('abas:', abas.join(', '));
  console.log('erros no console:', erros.length ? erros.join(' | ') : 'nenhum');
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
