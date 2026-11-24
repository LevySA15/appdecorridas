const h = require('./harness');
(async () => {
  const b = await h.browser();
  const { page } = await h.phone(b, { url: 'http://127.0.0.1:8081/index.html' });
  await page.waitForTimeout(1500);
  console.log(await page.evaluate(() => [...document.querySelectorAll('flt-semantics-host')].map(e => e.innerHTML).join('\n').slice(0, 3000)));
  await b.close();
})();
