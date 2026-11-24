const h = require('./harness');
(async () => {
  const b = await h.browser();
  const { page, logs } = await h.phone(b, { url: 'http://127.0.0.1:8081/index.html' });
  await page.waitForTimeout(1500);
  console.log(await h.shot(page, '00-login-claro'));
  console.log(await h.text(page));
  console.log(logs.join('\n'));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
