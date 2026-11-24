const h = require('./harness');
const { aprovar } = require('./fluxo');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const { page, logs } = await h.phone(b, { dark, url: 'http://127.0.0.1:8082/index.html', permissions: ['geolocation'] });
  const say = async (n) => { console.log(`--- ${n}`); console.log(await h.text(page)); await h.shot(page, `m-${tag}-${n}`); };
  await page.waitForTimeout(1200);
  const phone = '75977000001';
  await h.type(page, 'Telefone', phone);
  await h.tap(page, 'Enviar código');
  await page.waitForTimeout(800);
  await h.type(page, 'Código', await h.otp(phone));
  await h.tap(page, 'Entrar', { exact: true });
  await page.waitForTimeout(2500);
  await say('05-pendente');
  console.log('aprovando:', JSON.stringify(await aprovar('7000001')).slice(0, 200));
  await page.waitForTimeout(3000);
  if ((await h.text(page)).includes('Atualizar')) { await h.tap(page, 'Atualizar'); await page.waitForTimeout(2500); }
  await say('06-home-aprovado');
  console.log(logs.join('\n'));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
