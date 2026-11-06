# Painel: saques e avisos ao vivo (plano 4I) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, escolha do Levy) para implementar este plano tarefa a tarefa. Os passos usam caixas `- [ ]`.

**Goal:** (1) o dono vê os saques de saldo dos passageiros no painel; (2) um SOS, alerta de segurança ou recurso novo aparece **na hora** no painel aberto (hoje só aparece se alguém clicar em "Alertas"), com o título da aba avisando.

**Architecture:** só `server/painel/` (HTML/JS/CSS puros, sem compilação) mais testes de servidor que rodam o JavaScript no `node`. O painel passa a abrir o mesmo WebSocket `/v1/ws` dos apps (primeira mensagem `{"token"}`), que já entrega aos administradores os avisos `sos`, `safety_alert`, `safety_ok`, `mock_location_suspected` e `appeal_opened`.

**Tech Stack:** JavaScript sem biblioteca, WebSocket do navegador, pytest + node 20.

**Spec:** sem documento de desenho; o item vem do roteiro do 4A ("aviso no próprio site quando entra recurso ou alerta; tela de saques"). O Levy mandou (06/11/2026) "fazer no automático", então as decisões são minhas e ficam no roteiro.

## Global Constraints

- Regra de ouro do painel: texto vindo da API só entra na página por `esc()/money()/when()/attr()`; os testes que vigiam isso e a política de conteúdo (`default-src 'self'`, sem script nem estilo dentro da página) continuam valendo. O WebSocket é do mesmo endereço da página (`ws(s)://` + `location.host`).
- Nada de som nem de biblioteca nova. Nada de dado novo no servidor: nenhuma rota nova.
- O painel nunca foi aberto num navegador por quem o escreveu; o que dá para provar (lógica no `node`) é provado, o resto vai para o roteiro como "não visto".

## Review Focus

- Texto de aviso nunca entra como HTML (nomes e motivos vêm do servidor).
- A conexão ao vivo se refaz sozinha quando cai, não abre duas ao mesmo tempo e **para** quando a pessoa sai do painel ou a sessão acaba.
- Aviso que chega com a tela de alertas aberta atualiza a lista sem tirar a pessoa do lugar.

---

### Task 1: Tela "Saques"

**Files:** Modify `server/painel/painel.js` (`TELAS`, `VISOES.saques`, exportar `VISOES` e `TELAS`); Test `server/tests/api/test_painel_site.py`.

**Interfaces:** `VISOES.saques(): Promise<string>` lê `GET /v1/admin/withdrawals?limit=100` e monta a tabela "Quando · Passageiro · Valor · Chave" (tipo + chave mascarada, como o servidor manda). `TELAS.saques = "Saques"`, logo depois de "Dinheiro".

- [ ] **Step 1 (RED):** teste com `node`: stub de `fetch` devolvendo dois saques (um com nome `<b>Ana</b>`), chama `p.VISOES.saques()` e confere que a tabela traz `R$ 25,00`, o texto escapado `&lt;b&gt;Ana&lt;/b&gt;`, a chave mascarada e a coluna "Chave"; com lista vazia, "Nada por aqui."; e que `Object.keys(p.TELAS)` tem `saques` logo depois de `dinheiro`.
- [ ] **Step 2:** rodar. Expected: FAIL (`VISOES`/`TELAS` não exportados).
- [ ] **Step 3:** implementar e exportar.
- [ ] **Step 4:** `pytest tests/api/test_painel_site.py -q`. Expected: PASS (inclui "toda rota chamada pelo JavaScript existe na API" e a sintaxe).
- [ ] **Step 5:** commit `feat(painel): tela de saques`.

### Task 2: Avisos ao vivo

**Files:** Modify `server/painel/index.html` (um `<p id="alerta-vivo" role="alert" hidden>`), `server/painel/painel.css` (destaque), `server/painel/painel.js`; Test `server/tests/api/test_painel_site.py`.

**Interfaces (todas exportadas para teste):**
- `descreverAviso(mensagem: {type, data}) -> {texto: string, tela: "alertas"|"recursos", urgente: boolean} | null`: `sos` → urgente, "SOS pelo motoqueiro/passageiro" (conforme `data.raised_by`; sem o campo, "SOS"); `safety_alert` → "Alerta de segurança: parou / saiu da rota / sem sinal" conforme `data.kind`; `mock_location_suspected` → "Localização suspeita numa corrida"; `appeal_opened` → "Novo recurso de taxa de cancelamento" (tela `recursos`); `safety_ok`, `ready` e qualquer outro tipo → `null` (mas `safety_ok` pede só atualizar a lista, ver `aoAviso`).
- `conectarAvisos({criarSocket, agendar, token, aoMensagem}) -> {fechar()}`: abre `criarSocket()`, manda `JSON.stringify({token})` ao abrir, entrega cada mensagem JSON a `aoMensagem`, e ao cair agenda (`agendar(fn, 3000)`) uma nova conexão, até `fechar()` (que também fecha o socket e cancela a reconexão). Nunca há dois sockets vivos ao mesmo tempo.
- `aoAviso(mensagem)`: se `descreverAviso` devolver aviso, mostra o texto em `#alerta-vivo` (com `textContent`, nunca HTML), conta quantos chegaram desde a última vez (`(+N)`), muda `document.title` para `(!) <texto> — Painel do dono` (volta ao normal quando a pessoa clica no aviso) e, se a tela aberta for a do aviso (ou for `safety_ok`/`alertas`), recarrega a lista com `mostrar(telaAtual)`. Clicar no aviso leva à tela dele e o esconde.
- `iniciar()` abre a conexão (guarda o `{fechar}`), `sair()` e o 401 chamam `fechar()`.

- [ ] **Step 1 (RED):** testes com `node` e um `WebSocket` falso: (a) `descreverAviso` para cada tipo acima, incluindo texto com `<script>` em `data` (o texto devolvido é puro; o escape é do `textContent`) e tipo desconhecido → `null`; (b) `conectarAvisos`: a primeira mensagem enviada é o token, uma mensagem chega ao `aoMensagem`, depois de `onclose` aparece um agendamento de 3000 ms e, ao executá-lo, um **segundo** socket (e o primeiro já fechado); depois de `fechar()` o agendamento pendente não abre nada; (c) `aoAviso` com `document` falso: o texto vai para `textContent`, o título muda, o contador sobe com avisos seguidos e o clique limpa tudo.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** implementar. Endereço do socket: `(location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/v1/ws"`.
- [ ] **Step 4:** `pytest tests/api/test_painel_site.py tests/api/test_security_headers.py -q`. Expected: PASS (a política de conteúdo continua cabendo no painel).
- [ ] **Step 5:** commit `feat(painel): avisos ao vivo de SOS, alerta de segurança e recurso`.

### Task 3: Fechamento do lote

- [ ] Roteiro: linha do 4I e "Itens que sobraram do plano 4I" (não visto no navegador; sem som; política `connect-src` herda `default-src 'self'` — conferir `ws(s)` do mesmo endereço num navegador real); `docs/api-v1.md` se mudar algo (não deve); suíte do servidor; autorrevisão; mesclar (fast-forward), empurrar, apagar a branch e o registro.
