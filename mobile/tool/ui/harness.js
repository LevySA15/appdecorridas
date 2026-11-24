// Navegador sem janela (Chromium do Playwright) para conferir os apps Flutter na web: tira foto das telas e
// aperta botões pelo texto. Não depende de a janela do computador estar à vista (o Chrome do dia a dia, quando
// fica atrás de outra janela, não deixa tirar foto).
//
//   NODE_PATH=<pasta com playwright-core> node cenario.js
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const os = require('os');

const CHROME = process.env.CHROME_BIN || path.join(os.homedir(), '.cache/ms-playwright/chromium-1228/chrome-linux64/chrome');
const API = process.env.API_URL || 'http://127.0.0.1:8100';
const OUT = process.env.SHOTS || path.join(os.tmpdir(), 'corrida-shots');
fs.mkdirSync(OUT, { recursive: true });

async function browser() {
  return chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  });
}

/** Uma "tela de celular": 390x844, tema claro ou escuro. */
async function phone(b, { dark = false, url, width = 390, height = 844, permissions = [] } = {}) {
  const ctx = await b.newContext({
    viewport: { width, height }, deviceScaleFactor: 2, colorScheme: dark ? 'dark' : 'light', locale: 'pt-BR',
    permissions, geolocation: { latitude: -12.9644, longitude: -39.2597 },
  });
  const page = await ctx.newPage();
  const logs = [];
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) logs.push(`[${m.type()}] ${m.text()}`); });
  page.on('response', (r) => { if (r.status() >= 400) logs.push(`[http ${r.status()}] ${r.request().method()} ${r.url()}`); });
  page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`));
  await page.goto(url, { waitUntil: 'load' });
  await page.waitForSelector('flt-glass-pane', { state: 'attached', timeout: 60000 });
  await page.waitForSelector('flt-semantics-placeholder', { state: 'attached', timeout: 60000 });
  // acessibilidade do Flutter: sem isto a tela é só um desenho e não dá para achar botão pelo texto
  await page.evaluate(() => document.querySelector('flt-semantics-placeholder')?.click());
  await page.waitForSelector('flt-semantics', { state: 'attached', timeout: 30000 });
  await page.waitForTimeout(800);
  return { ctx, page, logs };
}

const norm = (s) => s.replace(/\s+/g, ' ').trim();

/** Aperta o elemento (botão, aba, texto) que tem este texto. */
async function tap(page, text, { exact = false, nth = 0, timeout = 8000 } = {}) {
  const pattern = exact ? new RegExp(`^\\s*${text}\\s*$`) : text;
  let target = page.locator('flt-semantics[role=button], flt-semantics[role=tab], flt-semantics[role=menuitem], flt-semantics[role=checkbox], flt-semantics[role=switch], flt-semantics[role=radio]').filter({ hasText: pattern });
  if ((await target.count()) === 0) target = page.locator('flt-semantics').filter({ hasText: pattern, hasNot: page.locator('flt-semantics') });
  if ((await target.count()) === 0) target = page.locator(`flt-semantics[aria-label*="${text}"]`);
  const el = target.nth(nth);
  await el.waitFor({ state: 'attached', timeout });
  await el.click({ force: true, timeout });
  await page.waitForTimeout(600);
}

/** Escreve no campo de texto com esse rótulo (o Flutter cria um <input> para cada campo). */
async function type(page, label, value) {
  const field = page.locator(`input[aria-label*="${label}"], textarea[aria-label*="${label}"]`).first();
  await field.waitFor({ state: 'attached', timeout: 8000 });
  await field.click({ force: true });
  await page.waitForTimeout(250);
  await page.keyboard.press('Control+A');
  await page.keyboard.type(value, { delay: 15 });
  await page.waitForTimeout(250);
}

/** Toque num ponto da tela (mapa). Com a acessibilidade ligada o Flutter transforma o toque em "toque no centro do
 * elemento"; por isso a camada de acessibilidade some por um instante. */
async function tapAt(page, x, y) {
  await page.evaluate(() => { document.querySelector('flt-semantics-host').style.visibility = 'hidden'; });
  await page.mouse.click(x, y);
  await page.evaluate(() => { document.querySelector('flt-semantics-host').style.visibility = ''; });
  await page.waitForTimeout(500);
}

async function text(page) {
  return await page.evaluate(() => [...document.querySelectorAll('flt-semantics')]
    .filter((e) => !e.querySelector('flt-semantics'))
    .map((e) => (e.getAttribute('aria-label') || e.textContent || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean).join(' | '));
}

async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  return file;
}

async function otp(phone) {
  const r = await fetch(`${API}/v1/dev/otp?phone=${encodeURIComponent(phone)}`);
  return (await r.json()).code;
}

module.exports = { browser, phone, tap, tapAt, type, text, shot, otp, OUT, API };

// ---- API como administrador (aprova cadastros e afins, sem abrir o painel) ----
async function admin(phone = '75 99999-0000') {
  return pessoa(phone, 'admin');
}

/** Entra pela API (sem tela) com um telefone e um papel; `call` já leva o token. */
async function pessoa(phone, role) {
  await fetch(`${API}/v1/auth/code`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone }) });
  const code = await otp(phone);
  const r = await fetch(`${API}/v1/auth/verify`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone, code, role, device: 'cenario' }) });
  const { token } = await r.json();
  const call = async (method, path, body) => {
    const resp = await fetch(`${API}${path}`, { method, headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    const txt = await resp.text();
    try { return JSON.parse(txt); } catch { return txt; }
  };
  return { call, token };
}
module.exports.admin = admin;
module.exports.pessoa = pessoa;
