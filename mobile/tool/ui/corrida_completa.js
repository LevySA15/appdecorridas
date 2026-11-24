// Uma corrida de ponta a ponta com os dois apps de verdade (cada um num "celular" próprio):
// passageiro pede → motoqueiro aceita, chega, confere o código, leva, finaliza → passageiro avalia.
const h = require('./harness');
const { entrar } = require('./fluxo');
const APP_P = 'http://127.0.0.1:8081/index.html';
const APP_M = 'http://127.0.0.1:8082/index.html';
const PAX = process.env.PAX || '75999990002';
const RIDER = '75977000001';

(async () => {
  const b = await h.browser();
  const dark = process.argv[2] === 'escuro';
  const tag = dark ? 'escuro' : 'claro';
  const metodo = process.argv[3] === 'pix' ? 'Pix' : 'Dinheiro';
  const P = await h.phone(b, { dark, url: APP_P });
  const M = await h.phone(b, { dark, url: APP_M, permissions: ['geolocation'] });
  const log = (who, msg) => console.log(`[${who}] ${msg}`);
  const snap = async (who, ctx, name) => { const t = await h.text(ctx.page); log(who, `${name}: ${t}`); await h.shot(ctx.page, `e2e-${tag}-${who}-${name}`); return t; };
  const wait = (page, re, ms = 30000) => page.waitForFunction((src) => {
    const t = [...document.querySelectorAll('flt-semantics')].filter((e) => !e.querySelector('flt-semantics')).map((e) => e.getAttribute('aria-label') || e.textContent || '').join(' | ');
    return new RegExp(src).test(t);
  }, re.source, { timeout: ms });

  // motoqueiro entra e liga o "estou rodando"
  await entrar(M.page, RIDER, null);
  await snap('M', M, '01-home');
  if ((await h.text(M.page)).includes('Ligue para receber')) await h.tap(M.page, 'Estou rodando');
  await M.page.waitForTimeout(2500);
  await snap('M', M, '02-rodando');

  // passageiro entra e pede
  await entrar(P.page, PAX, 'Maria Teste');
  await snap('P', P, '01-home');
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(1500);
  await h.tapAt(P.page, 150, 330);
  await h.tapAt(P.page, 260, 450);
  await wait(P.page, /Pedir corrida/);
  await snap('P', P, '02-cotacao');
  await h.tap(P.page, metodo);
  await h.tap(P.page, 'Pedir corrida', { exact: true });
  await P.page.waitForTimeout(2500);
  await snap('P', P, '03-procurando');

  // motoqueiro recebe a oferta
  await wait(M.page, /Aceitar/, 40000);
  await snap('M', M, '03-oferta');
  await h.tap(M.page, 'Aceitar');
  await M.page.waitForTimeout(2500);
  await snap('M', M, '04-a-caminho');
  await snap('P', P, '04-moto-a-caminho');
  await h.tap(M.page, 'Ir até o ponto de embarque').catch(() => {});
  await M.page.waitForTimeout(1000);
  await h.tap(M.page, 'Cheguei', { exact: true });
  await M.page.waitForTimeout(2500);
  await snap('M', M, '05-cheguei');
  const tp = await snap('P', P, '05-moto-chegou');
  const pin = (tp.match(/\b(\d{4})\b/) || [])[1];
  log('P', `PIN lido: ${pin}`);
  await h.tap(M.page, 'Confirmei o capacete extra');
  await M.page.waitForTimeout(1500);
  if (metodo === 'Pix') {
    log('P', 'pagando o Pix pelo servidor (rota de desenvolvimento)');
  }
  await h.type(M.page, 'Código do passageiro', pin);
  await snap('M', M, '06-codigo');
  await h.tap(M.page, 'Começar corrida');
  await M.page.waitForTimeout(2500);
  await snap('M', M, '07-em-viagem');
  await snap('P', P, '06-em-viagem');
  await h.tap(M.page, 'Ir até o destino').catch(() => {});
  await M.page.waitForTimeout(1000);
  await h.tap(M.page, 'Finalizar corrida');
  await M.page.waitForTimeout(3000);
  await snap('M', M, '08-finalizada');
  await snap('P', P, '07-fim');
  await h.tap(P.page, '5 estrelas');
  await P.page.waitForTimeout(2000);
  await snap('P', P, '08-avaliou');
  await h.tap(M.page, '4 estrelas');
  await M.page.waitForTimeout(2000);
  await snap('M', M, '09-avaliou');
  if (metodo === 'Dinheiro') {
    await h.tap(M.page, 'Recebi o dinheiro').catch((e) => log('M', 'sem botão de recebi: ' + e.message.split('\n')[0]));
    await M.page.waitForTimeout(2500);
    await snap('M', M, '10-recebido');
  }
  await snap('P', P, '09-home-final');
  log('P', 'erros: ' + P.logs.join(' || '));
  log('M', 'erros: ' + M.logs.join(' || '));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
