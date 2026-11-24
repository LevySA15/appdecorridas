const h = require('./harness');
const path = require('path');
const FOTO = path.join(__dirname, 'foto-teste.png');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const { page, logs } = await h.phone(b, { dark, url: 'http://127.0.0.1:8082/index.html' });
  const say = async (n) => { console.log(`--- ${n}`); console.log(await h.text(page)); await h.shot(page, `m-${tag}-${n}`); };
  await page.waitForTimeout(1200);
  const phone = '75977000001';
  await h.type(page, 'Telefone', phone);
  await h.tap(page, 'Enviar código');
  await page.waitForTimeout(800);
  await h.type(page, 'Código', await h.otp(phone));
  await h.tap(page, 'Entrar', { exact: true });
  await page.waitForTimeout(2500);
  await say('01-cadastro');
  await h.type(page, 'Nome completo', 'João da Moto');
  await h.type(page, 'CPF', '52998224725');
  await h.type(page, 'Número da CNH', '12345678900');
  await h.type(page, 'Placa da moto', 'ABC1D23');
  await h.type(page, 'Modelo da moto', 'Honda CG 160');
  await h.type(page, 'Validade da CNH', '31/12/2030');
  await h.type(page, 'Validade do documento da moto', '31/12/2030');
  await page.waitForTimeout(500);
  await say('02-cadastro-preenchido');
  for (const kind of [0, 1, 2]) {
    const [chooser] = await Promise.all([page.waitForEvent('filechooser', { timeout: 8000 }), h.tap(page, 'Tirar foto', { nth: 0 })]);
    await chooser.setFiles(FOTO);
    await page.waitForTimeout(800);
  }
  await say('03-fotos');
  await h.tap(page, 'Enviar cadastro');
  await page.waitForTimeout(3500);
  await say('04-enviado');
  console.log(logs.join('\n'));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
