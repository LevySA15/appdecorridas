// Telas do motoqueiro que o cenário da corrida não passa: cadastro (com máscaras), em análise, extrato do dia.
const h = require('./harness');
const { entrar } = require('./fluxo');
const path = require('path');
const FOTO = path.join(__dirname, 'foto-teste.png');
(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const log = (m) => console.log(m);

  // novo motoqueiro: formulário de cadastro com as máscaras
  const novo = '759770' + String(Date.now()).slice(-5);
  const M = await h.phone(b, { dark, url: 'http://127.0.0.1:8082/index.html' });
  const snap = async (ctx, name) => { const t = await h.text(ctx.page); log(`--- ${name}: ${t}`); await h.shot(ctx.page, `mt-${tag}-${name}`); return t; };
  await entrar(M.page, novo, null);
  await snap(M, '01-cadastro-vazio');
  await h.type(M.page, 'CPF', '52998224725');
  await h.type(M.page, 'Placa da moto', 'abc-1d23');
  await h.type(M.page, 'Validade da CNH', '31122030');
  await h.type(M.page, 'Número da CNH', '12345678900999');
  await h.tap(M.page, 'Enviar cadastro');          // com campos faltando: mostra os erros
  await M.page.waitForTimeout(800);
  await snap(M, '02-cadastro-com-erros');
  const valores = await M.page.evaluate(() => [...document.querySelectorAll('input')].map((i) => `${i.getAttribute('aria-label')}=${i.value}`));
  log('campos: ' + valores.join(' | '));

  // cadastro enviado por API e ainda sem aprovação: tela de espera
  const pend = '759771' + String(Date.now()).slice(-5);
  const P = await h.phone(b, { dark, url: 'http://127.0.0.1:8082/index.html' });
  await h.pessoa(pend, 'rider');
  const api = await h.pessoa(pend, 'rider');
  const fs = require('fs'); const foto = fs.readFileSync(FOTO); const keys = {};
  for (const kind of ['selfie', 'cnh', 'crlv']) { const r = await fetch(`${h.API}/v1/rider/documents/${kind}`, { method: 'PUT', headers: { authorization: `Bearer ${api.token}`, 'content-type': 'image/png' }, body: foto }); keys[kind] = (await r.json()).key; }
  const n = Number(String(Date.now()).slice(-6)) + 777;
  await api.call('POST', '/v1/rider/register', { name: 'Pedro Pendente', cpf: '11144477735', cnh_number: String(20000000000 + n), plate: 'PEN1D23', moto_model: 'Yamaha Factor', selfie_key: keys.selfie, cnh_photo_key: keys.cnh, crlv_key: keys.crlv, cnh_expires_on: '2030-12-31', crlv_expires_on: '2030-12-31' });
  await entrar(P.page, pend, null);
  await snap(P, '03-em-analise');

  // extrato do dia de quem já rodou
  const E = await h.phone(b, { dark, url: 'http://127.0.0.1:8082/index.html' });
  await entrar(E.page, process.env.RIDER || '75977000001', null);
  await h.tap(E.page, 'Extrato do dia');
  await E.page.waitForTimeout(2000);
  await snap(E, '04-extrato');
  log('erros: ' + [...M.logs, ...P.logs, ...E.logs].join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
