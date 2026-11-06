# Parâmetros do painel em formulário (plano 4J) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, escolha do Levy). Passos com caixas `- [ ]`.

**Goal:** a tela "Parâmetros" do painel deixa de ser um bloco de JSON cru e vira um formulário com nome em português para cada número, dinheiro em reais ("1,50", não 150) e Sim/Não para o que liga e desliga.

**Architecture:** só `server/painel/painel.js` (e testes). Nenhuma rota nova: continua `GET /v1/admin/config` e `PUT /v1/admin/config/{chave}`, e o servidor continua sendo quem recusa número sem sentido. Uma tabela `PARAMETROS` descreve cada campo (rótulo, tipo); campo que o servidor passar a ter sem rótulo aparece com o nome cru (nunca some) e um teste de servidor falha para lembrar de dar nome.

**Tech Stack:** JavaScript puro, pytest + node 20.

**Spec:** sem documento de desenho; pedido do Levy (06/11/2026): "fazer no automático o app inteiro". Decisões minhas no roteiro.

## Global Constraints

- Texto da API só entra na página por `esc()/money()/when()/attr()/raw()` (testes do painel vigiam); sem script nem estilo dentro da página (política de conteúdo).
- Tipos de campo: `cents` (mostra reais, grava centavos inteiros), `int` (inteiro), `float` (decimal com vírgula ou ponto), `bool` (Sim/Não), `json` (só as faixas de taxa, `fees.tiers`).

## Review Focus

- Dinheiro nunca vira número quebrado: "1,5" → 150, "0,005" → 1 (arredonda), vazio ou letra → erro com o nome do campo.
- Inteiro com casa decimal ("3,5") é recusado antes de ir ao servidor, com o nome do campo.
- Salvar um bloco manda **todos** os campos do bloco (inclusive os que não têm rótulo), nunca só os alterados.
- Rótulo ou valor com `<`/`"` nunca vira HTML.

---

### Task 1: Conversões e coleta do formulário

**Files:** Modify `server/painel/painel.js`; Test `server/tests/api/test_painel_site.py`.

**Interfaces:** `paraCampo(tipo, valor) -> string`; `doCampo(tipo, texto, rotulo) -> valor` (levanta `Error` em português com o rótulo); `coletarBloco(campos: {campo, tipo, rotulo, texto}[]) -> object`; `PARAMETROS: {chave: {titulo, campos: {nome: {rotulo, tipo}}}}`; exportados.

- [ ] **Step 1 (RED):** testes com `node`: `paraCampo("cents", 150) == "1,50"`, `("cents", 5000) == "50,00"`, `("int", 120) == "120"`, `("float", 0.8) == "0,8"`, `("bool", true) == "sim"`; `doCampo("cents", "1,5", "x") == 150`, `("cents", "1.50", "x") == 150`, `("cents", "0,005", "x") == 1`, `("int", " 120 ", "x") == 120`, `("float", "0,8", "x") == 0.8`, `("bool", "nao", "x") == false`; erros: `("cents", "", "Bandeirada")`, `("cents", "abc", "Bandeirada")` e `("int", "3,5", "Corridas de teste")` dizem o rótulo; `coletarBloco` monta o objeto e devolve o erro do primeiro campo ruim; guarda: para cada chave de `_TYPES`, o conjunto de campos de `PARAMETROS` é exatamente o das dataclasses (`PARAMETROS` não pode ter campo que não existe nem faltar um) e `fees.tiers` é `json`.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** implementar a tabela `PARAMETROS` (todos os campos de `app/domain/config.py`) e as funções.
- [ ] **Step 4:** `pytest tests/api/test_painel_site.py -q`. Expected: PASS.
- [ ] **Step 5:** commit `feat(painel): conversões do formulário de parâmetros`.

### Task 2: Tela de formulário

**Files:** Modify `server/painel/painel.js` (`VISOES.parametros`, `ACOES["config-save"]`), `server/painel/painel.css`; Test `server/tests/api/test_painel_site.py`.

- [ ] **Step 1 (RED):** teste com `node` e `fetch` falso: `VISOES.parametros()` com a resposta de `GET /v1/admin/config` monta um `<fieldset>` por bloco, com o rótulo em português, `1,50` no campo de dinheiro, `<select>` Sim/Não nos booleanos, um campo sem rótulo conhecido aparece com o nome cru e o rótulo `<b>x</b>` sai escapado; `ACOES["config-save"]("rides")` com `document.querySelectorAll` falso envia `PUT /v1/admin/config/rides` com os valores convertidos (centavos inteiros) e com erro de número ruim **não** chama o servidor.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** implementar. Cada campo: `<label>rótulo <input data-campo data-tipo data-rotulo value>` (ou `select`/`textarea`); botão "Salvar <título>" por bloco; o aviso do servidor ("a taxa de cancelamento precisa ser positiva…") aparece como já aparece hoje.
- [ ] **Step 4:** `pytest tests/api/test_painel_site.py tests/api/test_security_headers.py tests/api/test_admin_panel_write.py -q`. Expected: PASS.
- [ ] **Step 5:** conferência num Chrome de verdade com o servidor descartável (abrir Parâmetros, mudar a bandeirada, salvar, recarregar, ver o valor; tentar um valor ruim e ver a mensagem). Commit `feat(painel): parâmetros em formulário`.

### Task 3: Fechamento

- [ ] Roteiro (linha 4J e "Itens que sobraram"), suíte `tests/api`, mesclar (fast-forward), empurrar, apagar branch e registro.
