# Reenviar cadastro recusado e renovar documentos que desbloqueia — Plano de implementação (plano 5C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cumprir as duas respostas do Levy (25/10/2026) às perguntas que o plano 5B deixou: (1) **renovar os documentos desbloqueia a conta sozinho** quando o bloqueio foi por "documento vencido"; (2) **cadastro recusado pode ser reenviado**. Servidor e app do motoqueiro.

**Architecture:** Duas mudanças pequenas em `server/app/services/riders.py` (regra), uma linha em `docs/api-v1.md` para cada, e no app do motoqueiro: a tela raiz de um cadastro recusado passa a ser o formulário (com o motivo no alto) e o aviso do servidor vira mensagem. Nenhuma rota nova; as rotas `POST /v1/rider/documents/renew` e `POST /v1/rider/register` ficam com o mesmo formato.

**Tech Stack:** Python/FastAPI/SQLAlchemy + pytest (servidor), Flutter (app).

**Spec:** `docs/api-v1.md` (seção "Motoqueiro") e a seção "Itens que sobraram do plano 5B" do roteiro (as perguntas 1 e 2 e a resposta do Levy: "Deve. Pode ser reenviado.").

## Decisões deste plano (minhas, dentro das respostas do Levy)

1. **O que conta como "bloqueado por documento vencido":** `status == "blocked"`, `rejected_reason == "documento vencido"` **e** `UserRow.is_blocked == False`. A varredura de documentos vencidos (`block_expired_documents`) marca o motivo mas **não** liga `is_blocked`; já o bloqueio do administrador (`block()`) liga `is_blocked` e escreve o motivo que ele digitou. Assim, um bloqueio do administrador nunca sai por renovar documentos, nem se o texto do motivo for igual. O texto vira uma constante usada nos dois lugares.
2. **Renovar só desbloqueia se as duas datas novas valem** (a regra de hoje já recusa data vencida com `RegistrationError`; nada muda nisso).
3. **Reenviar o cadastro recusado reaproveita a mesma linha** (mesmo `user_id`): atualiza dados, fotos e validades, volta para `pending` e apaga o motivo. CPF, CNH e placa continuam únicos entre motoqueiros, mas não colidem com o próprio cadastro.
4. **Contato de suporte:** o Levy vai comprar um número e criar um e-mail na hospedagem quando abrir o CNPJ. Até lá o app **não mostra** "fale com o suporte" (some da tela de recusa, que agora é o formulário). Fica no roteiro para pôr o contato nas telas de bloqueio quando existir.

## Global Constraints

- Servidor: TDD com pytest a partir de `server/` (`.venv/bin/pytest`); migração de banco **não** é necessária (nenhuma coluna nova).
- Mensagens para a pessoa em português do Brasil; nomes de código em inglês.
- App: comandos a partir de `mobile/` com `export PATH="$HOME/development/flutter/bin:$PATH"`; mesmas regras de teste do 5B (`tester.runAsync(() => controller.signOut())` dentro do corpo do teste).
- Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; direto na `main`; um comando de git por vez.

## Review Focus

1. **O bloqueio do administrador não pode sair por renovar documentos**, nem com o mesmo texto de motivo, nem com `is_blocked` desligado por outro caminho. Tarefa 1.
2. **Reenviar o cadastro não pode roubar nem duplicar dados de outro motoqueiro** (CPF, CNH, placa) e não pode reabrir cadastro pendente, aprovado ou bloqueado. Tarefa 2.
3. **Dois toques seguidos em "Enviar cadastro" depois de recusado** não podem criar linhas duplicadas nem deixar o cadastro em estado estranho (a trava `with_for_update` do perfil e o `IntegrityError` tratados). Tarefa 2.
4. **O app não pode ficar sem saída** em nenhum estado do cadastro (recusado → formulário; bloqueado → renovar; pendente → atualizar). Tarefa 3.

---

### Task 1: Renovar documentos desbloqueia quem foi bloqueado por documento vencido

**Files:**
- Modify: `server/app/services/riders.py` (`renew_documents`, `block_expired_documents`; constante `EXPIRED_DOCUMENTS_REASON`), `docs/api-v1.md`
- Test: `server/tests/services/test_riders.py`

**Interfaces:**
- Produces: `EXPIRED_DOCUMENTS_REASON = "documento vencido"` em `app/services/riders.py`. `RiderService.renew_documents(...)` mantém a assinatura; quando o motoqueiro está bloqueado só por documento vencido (decisão 1) e as datas novas valem, passa a `approved`, apaga `rejected_reason` e emite o aviso `rider_unblocked`.

- [ ] **Step 1: Testes que falham** (`test_riders.py`, no molde de `test_documentos_vencidos_bloqueiam_e_tiram_da_disponibilidade`; `HOJE = 2026-10-09`, a varredura roda com `dt.date(2027, 1, 1)`):
  - `test_renovar_documentos_libera_quem_foi_bloqueado_por_documento_vencido`: motoqueiro aprovado com `crlv_expires_on=2026-12-31`, varredura em 2027-01-01 bloqueia; `renew_documents(..., cnh_expires_on=2032-01-01, crlv_expires_on=2031-01-01, today=2027-01-01)`; depois `status == "approved"`, `rejected_reason is None`, `online is False`, o último aviso é `rider_unblocked`, e `go_online(session, "r1", 2027-01-01)` funciona.
  - `test_renovar_documentos_nao_libera_o_bloqueio_do_administrador`: aprovado, `service.block(session, "r1", "documento vencido")` (mesmo texto!), renovar com datas boas: continua `blocked`, `UserRow.is_blocked is True`, nenhum `rider_unblocked` novo.
  - `test_renovar_com_data_vencida_continua_bloqueado`: bloqueado pela varredura, renovar com `crlv_expires_on` anterior a `today` levanta `RegistrationError` e o status segue `blocked`.
  - `test_renovar_documentos_de_quem_nao_esta_bloqueado_nao_emite_aviso`: aprovado normal, renovar não emite `rider_unblocked` (o teste existente `test_renovar_documentos_atualiza_as_datas` continua passando).
- [ ] **Step 2:** `cd server && .venv/bin/pytest tests/services/test_riders.py -q`. Expected: os três primeiros novos falham (o primeiro por continuar `blocked`).
- [ ] **Step 3: Implementar** (constante + a condição da decisão 1 dentro de `renew_documents`, depois de gravar as datas; `session.get(UserRow, rider_id)` para ler `is_blocked`; `self.events.add(rider_id, "rider_unblocked")`). `block_expired_documents` passa a usar a constante.
- [ ] **Step 4:** `.venv/bin/pytest tests/services/test_riders.py tests/api/test_rider_onboarding.py -q` e depois `.venv/bin/pytest -q` (suíte inteira). Expected: tudo passa.
- [ ] **Step 5:** em `docs/api-v1.md`, na linha de `POST /v1/rider/documents/renew`, acrescentar: "Se a conta estava bloqueada só por documento vencido, volta a `approved` (aviso `rider_unblocked`); bloqueio do administrador não sai por aqui." **Commit** `feat(servidor): renovar documentos desbloqueia quem foi bloqueado por documento vencido`.

---

### Task 2: Cadastro recusado pode ser reenviado

**Files:**
- Modify: `server/app/services/riders.py` (`register_rider`, `_find_duplicate`), `docs/api-v1.md`
- Test: `server/tests/services/test_riders.py`, `server/tests/api/test_rider_onboarding.py`

**Interfaces:**
- Produces: `RiderService.register_rider(...)` mantém a assinatura. Com `RiderProfileRow` existente e `status == "rejected"`, atualiza a mesma linha (decisão 3) e volta para `pending`; com qualquer outro status continua levantando `RegistrationError("Seu cadastro já foi enviado.")`. `_find_duplicate(session, *, cpf, cnh_number, plate, exclude_user_id: str | None = None)` ignora o próprio cadastro.

- [ ] **Step 1: Testes que falham** (`test_riders.py`):
  - `test_cadastro_recusado_pode_ser_reenviado`: cadastrar, `reject(..., "Foto da CNH ilegível")`, cadastrar de novo com nome, modelo e fotos diferentes: `status == "pending"`, `rejected_reason is None`, campos novos gravados (inclusive o nome do `UserRow`), e só existe 1 `RiderProfileRow`.
  - `test_reenviar_com_o_mesmo_cpf_e_placa_do_proprio_cadastro_funciona`: recusado e reenviado com os mesmos CPF/CNH/placa não levanta `DuplicateRegistration`.
  - `test_reenviar_com_dado_de_outro_motoqueiro_e_recusado`: outro motoqueiro aprovado com `CPF2`; o recusado reenvia com `CPF2` → `DuplicateRegistration` (campo `cpf`) e continua `rejected`.
  - `test_pendente_aprovado_e_bloqueado_nao_reenviam`: para cada um desses status, cadastrar de novo levanta `RegistrationError` com "já foi enviado".
  - `test_reenvio_com_dado_ruim_continua_recusado_com_mensagem`: recusado reenvia com CPF inválido → `RegistrationError` e o perfil continua `rejected` com o motivo antigo.
  `test_rider_onboarding.py` (API; no molde dos testes de cadastro dali): `test_motoqueiro_recusado_reenvia_o_cadastro_pela_api` — registra, o administrador recusa, o motoqueiro envia fotos novas e `POST /v1/rider/register` responde 201 `{"status":"pending"}`; `GET /v1/rider/state` mostra `registration.status == "pending"` e `reason` nulo.
- [ ] **Step 2:** `.venv/bin/pytest tests/services/test_riders.py tests/api/test_rider_onboarding.py -q`. Expected: os novos falham ("Seu cadastro já foi enviado").
- [ ] **Step 3: Implementar.** No caminho do recusado: conferir duplicidade com `exclude_user_id`, gravar os campos novos na linha existente dentro de `session.begin_nested()` com `session.flush()` e o mesmo tratamento de `IntegrityError` do cadastro novo (devolve `DuplicateRegistration`/"já foi enviado"); o perfil já é lido com `with_for_update` por `_profile`, então dois toques seguidos são serializados (o segundo vê `pending` e recebe "já foi enviado").
- [ ] **Step 4:** `.venv/bin/pytest -q` (suíte inteira). Expected: tudo passa.
- [ ] **Step 5:** em `docs/api-v1.md`, na linha de `POST /v1/rider/register`, acrescentar: "Cadastro **recusado** pode ser reenviado (mesma rota; volta a `pending`); pendente, aprovado e bloqueado respondem que já foi enviado." **Commit** `feat(servidor): cadastro recusado pode ser reenviado`.

---

### Task 3: App do motoqueiro — formulário para o recusado, aviso e renovar que libera

**Files:**
- Modify: `mobile/apps/rider/lib/screens/registration_screen.dart` (parâmetro `rejectionReason`), `lib/screens/status_screen.dart` (tira o ramo "recusado"; ajusta o texto de bloqueado), `lib/app.dart` (`_root`: `rejected` → formulário; avisos novos)
- Test: `mobile/apps/rider/test/screens/registration_screen_test.dart`, `test/screens/status_screen_test.dart`, `test/app_test.dart`

**Interfaces:**
- Produces: `RegistrationScreen({..., String? rejectionReason})` — quando não é `null`, mostra no alto "Seu cadastro foi recusado: {motivo}. Corrija e envie de novo." (sem o ": {motivo}" se vier vazio). `StatusScreen` deixa de tratar `rejected` (o app nunca a mostra para esse status) e o texto de bloqueado vira "Se o bloqueio foi por documento vencido, envie o documento novo e a conta é liberada na hora." Avisos do tempo real (mensagem): `rider_unblocked` → "Sua conta foi liberada."; `rider_rejected` → "Seu cadastro foi recusado. Veja o motivo e envie de novo."; `rider_blocked` → "Sua conta foi bloqueada."; `documents_expired` → "Um documento seu venceu. Envie o novo para voltar a receber corridas.".

- [ ] **Step 1: Testes que falham.**
  - `registration_screen_test`: `'recusado mostra o motivo no alto'` (`rejectionReason: 'Foto da CNH ilegível.'` → o texto "Seu cadastro foi recusado: Foto da CNH ilegível. Corrija e envie de novo."); `'sem motivo mostra so o aviso de recusado'` (`rejectionReason: ''`); sem o parâmetro, nenhum aviso de recusa.
  - `status_screen_test`: tirar o teste do "recusado" (o ramo deixa de existir) e ajustar o texto esperado de bloqueado.
  - `app_test`: `'recusado cai no formulario com o motivo'` (state `rejected` com `reason`: aparece `RegistrationScreen`, não `StatusScreen`); `'renovar de quem esta bloqueado por documento vencido libera a conta'` (o `POST /v1/rider/documents/renew` troca o `stateJson` para aprovado; depois de enviar, `RenewDocumentsScreen` some e aparece a `HomeScreen`); `'avisos do servidor viram mensagem'` para `rider_unblocked` e `rider_rejected`.
- [ ] **Step 2:** `cd mobile/apps/rider && flutter test test/screens/registration_screen_test.dart test/screens/status_screen_test.dart test/app_test.dart`. Expected: os novos falham.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** `flutter test` (app inteiro) e `flutter analyze` em `mobile/`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): motoqueiro recusado reenvia o cadastro e renovar documentos libera a conta`.

---

### Task 4: Roteiro e memória

**Files:**
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`

- [ ] **Step 1:** nova linha "5C … feito" na tabela; na seção "Itens que sobraram do plano 5B", trocar as três perguntas pelas respostas do Levy (1: "Deve" → feito no 5C; 2: "Pode ser reenviado" → feito no 5C; 3: contato de suporte → "quando criar o CNPJ ele compra um número e cria um e-mail na hospedagem"; pendente: pôr o contato nas telas de bloqueio quando existir).
- [ ] **Step 2:** suítes inteiras (servidor `.venv/bin/pytest -q`; `dart test` no `corrida_core`; `flutter test` nos pacotes e apps; `flutter analyze`). **Commit** `docs: plano 5C no roteiro` e `git push`.
