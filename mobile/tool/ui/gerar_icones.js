// Gera os ícones dos apps (PNG 1024) com a moto da fonte Material, usando o navegador sem janela.
// node gerar_icones.js <pasta de saída>
const h = require('./harness');
const fs = require('fs'); const path = require('path'); const os = require('os');
const FONTE = path.join(os.homedir(), 'development/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
const FONT_B64 = fs.readFileSync(FONTE).toString('base64');
const out = process.argv[2];
fs.mkdirSync(out, { recursive: true });
const html = (bg, fg, tamanhoMoto) => `<!doctype html><style>
@font-face { font-family: MI; src: url(data:font/otf;base64,${FONT_B64}); }
html,body{margin:0;width:1024px;height:1024px;background:${bg}}
.i{font-family:MI;font-size:${tamanhoMoto}px;line-height:1024px;text-align:center;color:${fg};width:1024px;height:1024px;display:block;font-feature-settings:'liga'}
</style><span class="i">&#xf025e;</span>`;
(async () => {
  const b = await h.browser();
  const ctx = await b.newContext({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const feitos = [
    ['passageiro', '#D92D27', '#FFFFFF', 640, false],          // ícone cheio: fundo vermelho, moto branca
    ['passageiro_fg', 'transparent', '#FFFFFF', 520, true],    // primeiro plano do ícone adaptativo (miolo seguro)
    ['motoqueiro', '#14161A', '#D92D27', 640, false],           // motoqueiro: fundo preto, moto vermelha (para distinguir os dois na tela)
    ['motoqueiro_fg', 'transparent', '#D92D27', 520, true],
  ];
  for (const [nome, bg, fg, tam, transparente] of feitos) {
    await page.setContent(html(bg, fg, tam));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(out, `${nome}.png`), omitBackground: transparente });
  }
  await b.close();
  console.log('ok', fs.readdirSync(out).join(', '));
})();
