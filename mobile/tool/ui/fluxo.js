// Passos comuns dos cenários: entrar como passageiro / motoqueiro pela tela.
const h = require('./harness');
async function entrar(page, telefone, nome) {
  await page.waitForTimeout(1200);
  await h.type(page, 'Telefone', telefone);
  await h.tap(page, 'Enviar código');
  await page.waitForTimeout(800);
  await h.type(page, 'Código', await h.otp(telefone));
  await h.tap(page, 'Entrar', { exact: true });
  await page.waitForTimeout(2000);
  if (nome && (await h.text(page)).includes('Como podemos te chamar')) {
    await h.type(page, 'Seu nome', nome);
    await h.tap(page, 'Continuar');
    await page.waitForTimeout(2200);
  }
}

/** Aprova pela API o cadastro pendente do motoqueiro com este telefone (o painel faz a mesma chamada). */
async function aprovar(telefoneFinal) {
  const adm = await h.admin();
  const lista = await adm.call('GET', '/v1/admin/riders?status=pending');
  const itens = Array.isArray(lista) ? lista : lista.riders || lista.items || [];
  const achou = itens.find((r) => String(r.phone || '').endsWith(telefoneFinal));
  if (!achou) throw new Error('cadastro pendente não achado: ' + JSON.stringify(lista).slice(0, 300));
  const id = achou.rider_id || achou.id || achou.user_id;
  return adm.call('POST', `/v1/admin/riders/${id}/approve`, {});
}
module.exports = { entrar, aprovar };
