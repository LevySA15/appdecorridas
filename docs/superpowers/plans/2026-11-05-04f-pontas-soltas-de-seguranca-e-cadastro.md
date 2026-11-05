# Pontas soltas de segurança e cadastro (plano 4F) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar quatro itens adiados que não dependem de CNPJ nem de chaves: SOS do motoqueiro, rastro da liberação automática por documento renovado, painel que mostra reenvio de cadastro com o motivo da recusa anterior, e limpeza das fotos de documentos que ninguém mais usa (LGPD).

**Architecture:** Mesma estrutura de sempre: serviço em `server/app/services`, rota fina em `server/app/api/routes`, uma migração (0011), site do painel em `server/painel`, cliente Dart em `mobile/packages/corrida_core` e tela no `mobile/apps/rider`. Nada novo de infraestrutura: a limpeza de fotos roda na tarefa diária do agendador que já existe.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest; Flutter 3.47 / Dart, `flutter_test`.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seção 9, segurança; seção 4, cadastro do motoqueiro). Origem dos itens: roteiro `2026-10-08-00-roteiro-dos-planos.md`, seções "Itens que sobraram do plano 5B/5C" e "Feito depois do 5C".

## Global Constraints

- Textos para o usuário em português do Brasil, simples. Nomes de código em inglês, comentários em português (padrão do repositório).
- Dinheiro em centavos; tempo em segundos (`float`, época Unix) vindo de `unit.now`/`runtime.clock`, nunca `time.time()` dentro de serviço.
- Toda escrita do administrador continua passando por `log_admin_action`.
- O banco de teste é o `t_<aleatório>` do `tests/conftest.py`; migrações novas precisam passar pelo teste de migração que já existe.
- Fotos de documento nunca saem sem login (`app/api/routes/files.py` não muda).
- O 190 é ligado pelo próprio app (como no passageiro); o servidor só avisa a central.

## Decisões deste plano (minhas, para o Levy conferir)

1. **SOS do motoqueiro avisa só os administradores**, não o passageiro (o perigo pode ser o próprio passageiro). O motoqueiro não tem contato de emergência cadastrado.
2. Vale nas mesmas fases do SOS do passageiro (`accepted`, `arrived`, `in_progress`) e repetir dentro de 5 minutos não cria outro alerta nem avisa de novo.
3. O SOS do motoqueiro **não mexe** nos avisos "está tudo bem?" abertos do passageiro.
4. A liberação automática por documento renovado entra no **registro do painel** com o próprio motoqueiro como autor (ação `rider.auto_unblock`); não existe administrador nessa ação.
5. Fotos de cadastro **recusado** são apagadas **30 dias** depois da recusa; fotos que nenhum cadastro usa (trocadas no reenvio/renovação, ou enviadas e abandonadas) são apagadas **24 horas** depois do envio. Os dois prazos são constantes em `app/services/document_cleanup.py`. Prazo de retenção é pergunta para o advogado (LGPD).

## Review Focus

- SOS fora da corrida (procurando, concluída, cancelada) → 409, sem alerta.
- SOS de um motoqueiro que não é o da corrida → 403 (`NotYourRide`), sem alerta.
- SOS repetido em 5 minutos → mesmo alerta, `repeated: true`, administradores avisados uma vez só; e SOS do passageiro e do motoqueiro na mesma corrida são alertas separados.
- Limpeza nunca apaga foto referenciada por algum cadastro nem arquivo com menos de 24 h; erro ao apagar um arquivo não impede apagar os outros nem derruba a tarefa diária.
- Cadastro recusado e reenviado duas vezes: contador 2 e motivo anterior = o da última recusa.
- Painel escapa o motivo anterior (texto digitado por um administrador).

## File Structure

- Create: `server/migrations/versions/0011_pontas_soltas_4f.py`, `server/app/services/document_cleanup.py`, `server/tests/services/test_document_cleanup.py`
- Modify: `server/app/db/models.py`, `server/app/services/riders.py`, `server/app/services/safety.py`, `server/app/db/queries.py`, `server/app/infra/documents.py`, `server/app/scheduler.py`, `server/app/api/routes/admin.py`, `server/app/api/routes/rider.py`, `server/painel/painel.js`, `docs/api-v1.md`
- Modify (Dart): `mobile/packages/corrida_core/lib/src/rider_api.dart`, `.../models/rider.dart`, `mobile/apps/rider/lib/rider_controller.dart`, `mobile/apps/rider/lib/app.dart`, `mobile/apps/rider/lib/screens/ride_screen.dart` e os testes correspondentes

---

### Task 1: Migração 0011 e modelos

**Files:**
- Create: `server/migrations/versions/0011_pontas_soltas_4f.py`
- Modify: `server/app/db/models.py` (`SafetyAlertRow`, `RiderProfileRow`)
- Test: `server/tests/db/` (o teste de migração existente; acrescentar a verificação das colunas novas)

**Interfaces:**
- Produces: `SafetyAlertRow.raised_by: str` (`'system'|'passenger'|'rider'`, padrão `'system'`, check `alert_raised_by_valid`); `RiderProfileRow.rejected_at: float | None`, `RiderProfileRow.previous_rejection: str | None` (200), `RiderProfileRow.resubmissions: int` (padrão 0).

- [ ] **Step 1: Escrever o teste que falha** — no teste de migração existente, depois de migrar até a cabeça, `inspect` mostra as 4 colunas novas e a constraint `alert_raised_by_valid`; inserir um alerta com `raised_by='xpto'` levanta `IntegrityError`.
- [ ] **Step 2: Rodar e ver falhar** — `cd server && .venv/bin/pytest tests/db -q -k migra` → FAIL (colunas não existem).
- [ ] **Step 3: Implementar** `0011` (`revision="0011"`, `down_revision="0010"`): `ALTER` das duas tabelas; `UPDATE safety_alerts SET raised_by='passenger' WHERE kind='sos'`; `UPDATE rider_profiles SET rejected_at = extract(epoch from now()) WHERE status='rejected'`; `downgrade` desfaz tudo. Espelhar as colunas em `models.py` (`server_default`).
- [ ] **Step 4: Rodar** `pytest tests/db -q` → PASS. Aplicar no banco de desenvolvimento: `.venv/bin/alembic upgrade head`.
- [ ] **Step 5: Commit** — `feat(servidor): migração 0011 (quem pediu o alerta, recusa e reenvio do cadastro)`

---

### Task 2: Recusa, reenvio e liberação automática no serviço do motoqueiro

**Files:**
- Modify: `server/app/services/riders.py`, `server/app/db/queries.py` (`RiderListItem`, `list_riders`), `server/app/api/routes/admin.py` (lista de motoqueiros e chamada de `reject`), chamadas existentes de `reject`/`renew_documents` nos testes e na rota `rider.py`
- Test: `server/tests/services/test_riders.py`, `server/tests/api/test_admin_panel_read.py`, `server/tests/api/test_rider_onboarding.py`

**Interfaces:**
- Consumes: colunas da Task 1; `log_admin_action(session, admin_id, action, target_type, target_id, detail, now)`.
- Produces: `RiderService.reject(session, rider_id, reason, now: float)` (grava `rejected_at=now`); `RiderService.renew_documents(..., now: float)` (parâmetro novo, por nome); `register_rider` num cadastro recusado grava `previous_rejection = <motivo da recusa>`, `resubmissions += 1`, `rejected_at = None`; `RiderListItem.resubmissions: int` e `.previous_rejection: str | None`; `GET /v1/admin/riders` devolve as duas chaves.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_recusar_grava_a_hora_da_recusa`: depois de `reject(..., now=500.0)`, `rejected_at == 500.0`.
  - `test_reenviar_guarda_o_motivo_anterior_e_conta_o_reenvio`: recusa "Foto da CNH ilegível", reenvia → `(previous_rejection, resubmissions, rejected_reason, rejected_at) == ("Foto da CNH ilegível", 1, None, None)`.
  - `test_reenviar_duas_vezes_conta_dois_e_guarda_o_ultimo_motivo`: recusa "A", reenvia, recusa "B", reenvia → `(previous_rejection, resubmissions) == ("B", 2)`.
  - `test_cadastro_novo_nao_tem_reenvio`: `(previous_rejection, resubmissions) == (None, 0)`.
  - `test_liberacao_automatica_deixa_rastro_no_registro`: no cenário `bloqueado_por_documento_vencido` + `renew_documents(... now=700.0)` com foto nova, `list_admin_actions(session, 10, 0)` tem uma linha `action == "rider.auto_unblock"`, `target_id == "r1"`, `admin_id == "r1"`, `at == 700.0`; renovar **sem** liberar (aprovado normal) não grava nada.
  - Na lista do painel (`test_admin_panel_read`): motoqueiro reenviado aparece com `resubmissions == 1` e `previous_rejection == "<motivo>"`.
- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/services/test_riders.py tests/api/test_admin_panel_read.py -q`.
- [ ] **Step 3: Implementar** os campos e as assinaturas acima. `reject` ganha `now` (atualizar todas as chamadas: rota do administrador usa `unit.now`; testes passam `now=` ou o valor posicional). `renew_documents` chama `log_admin_action(session, rider_id, "rider.auto_unblock", "rider", rider_id, "documentos renovados", now)` só quando `unblocks`. A rota `POST /v1/rider/documents/renew` passa `now=unit.now`.
- [ ] **Step 4: Rodar** os mesmos testes + `pytest tests/api/test_rider_onboarding.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(servidor): reenvio de cadastro guarda o motivo anterior e a liberação automática deixa rastro`

---

### Task 3: SOS do motoqueiro

**Files:**
- Modify: `server/app/services/safety.py`, `server/app/db/queries.py` (`SafetyAlertItem`, `list_safety_alerts`), `server/app/api/routes/rider.py`, `server/app/api/routes/admin.py`
- Test: `server/tests/services/test_safety.py`, `server/tests/api/test_safety_routes.py`

**Interfaces:**
- Produces: `SafetyService.rider_sos(session, rider_id: str, ride_id: str, now: float) -> RiderSosResult(alert_id: int, repeated: bool)`; `POST /v1/rider/rides/{ride_id}/sos` → `200 {"alert_id": int, "repeated": bool, "emergency_number": "190"}`; evento aos administradores `sos` ganha a chave `raised_by` (`"passenger"` ou `"rider"`); `GET /v1/admin/safety-alerts` ganha `raised_by`.
- O `sos` do passageiro passa a gravar `raised_by="passenger"` e a procurar o "SOS anterior" só entre os `raised_by="passenger"`.

- [ ] **Step 1: Escrever os testes que falham** (serviço, no cenário `mundo`)
  - `test_sos_do_motoqueiro_avisa_so_os_administradores`: `rider_sos(session, "r1", "ride-1", AGORA)` cria alerta `kind="sos"`, `status="sos"`, `raised_by="rider"`; `tipos(events, "adm-1") == tipos(events, "adm-2") == ["sos"]` com `data["raised_by"] == "rider"`; nenhum evento para `"p1"`; `notifier` sem mensagens.
  - `test_sos_do_motoqueiro_repetido_nao_cria_outro_alerta`: segunda chamada 60 s depois → mesmo `alert_id`, `repeated is True`, administradores com um aviso só; depois de 301 s cria outro.
  - `test_sos_do_motoqueiro_e_do_passageiro_sao_alertas_separados`: passageiro faz SOS, motoqueiro faz SOS → dois alertas com `raised_by` diferentes e o do motoqueiro com `repeated is False`.
  - `test_sos_do_motoqueiro_nao_mexe_no_aviso_aberto_do_passageiro`: com um alerta `open` (parada longa), depois do SOS ele continua `open`.
  - `test_sos_do_motoqueiro_so_na_corrida_e_so_do_proprio_motoqueiro`: corrida concluída → `InvalidTransition`; `rider_sos(session, "r-outro", ...)` → `NotYourRide`; nenhum alerta criado nos dois casos.
  - Rota (`test_safety_routes`): `POST /v1/rider/rides/{id}/sos` com a corrida iniciada → 200 com as 3 chaves e `emergency_number == "190"`; o administrador recebe `sos` com `raised_by == "rider"`; `GET /v1/admin/safety-alerts?status=sos` traz `raised_by == "rider"`; passageiro chamando essa rota → 403; fora da corrida → 409.
- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/services/test_safety.py tests/api/test_safety_routes.py -q`.
- [ ] **Step 3: Implementar** `rider_sos` espelhando `sos` sem o contato (chave de repetição `f"{ride_id}:sos:rider"`, `SOS_REPEAT_S`; posição vem de `self.positions.get(rider_id)`); rota fina em `rider.py` usando `unit.safety.rider_sos`; incluir `raised_by` em `SafetyAlertItem` e na resposta do administrador; acrescentar `raised_by` no payload do evento `sos` do passageiro.
- [ ] **Step 4: Rodar** os mesmos testes + `pytest tests/api/test_dia_pela_api.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(servidor): SOS do motoqueiro (avisa só a central)`

---

### Task 4: Limpeza das fotos de documentos

**Files:**
- Create: `server/app/services/document_cleanup.py`, `server/tests/services/test_document_cleanup.py`
- Modify: `server/app/infra/documents.py`, `server/app/scheduler.py`
- Test: `server/tests/infra/test_documents.py` (existente ou novo), `server/tests/services/test_document_cleanup.py`, `server/tests/api/test_scheduler.py`

**Interfaces:**
- Produces em `documents.py`: `StoredDocument(key: str, modified_at: float)` (dataclass congelada); `DocumentStore.list_all() -> list[StoredDocument]`; `DocumentStore.delete(key: str) -> None` (chave inexistente ou inválida não dá erro).
- Produces em `document_cleanup.py`: constantes `ORPHAN_AFTER_S = 86_400.0`, `REJECTED_KEEP_S = 30 * 86_400.0`; `PurgeReport(rejected: int, orphans: int)`; `release_rejected_photos(session, now: float) -> list[str]` (anula `selfie_key/cnh_photo_key/crlv_key` dos cadastros `rejected` com `rejected_at <= now - REJECTED_KEEP_S` e devolve as chaves a apagar); `referenced_keys(session) -> set[str]`; `delete_unreferenced(store, referenced: set[str], now: float) -> int` (apaga só arquivos fora de `referenced` com `modified_at <= now - ORPHAN_AFTER_S`; engole erro por arquivo e segue).
- Produces em `scheduler.py`: `run_daily_purge(runtime) -> PurgeReport | None` (marca `"purge"` em `runtime.job_marks` com a data local; `None` se hoje já rodou; não marca o dia se falhar) chamada em `Scheduler.tick` junto da tarefa diária, dentro de `_safely`.

- [ ] **Step 1: Escrever os testes que falham**
  - Loja local (`tmp_path`): `save` três fotos; `list_all()` devolve as três chaves com `modified_at` perto do mtime do arquivo; `delete(chave)` remove; `delete` de chave inexistente e de `"../../etc/passwd"` não levanta nem toca fora da pasta.
  - `test_recusado_ha_mais_de_30_dias_perde_as_fotos`: cadastro `rejected` com `rejected_at = now - 31 dias` → `release_rejected_photos` devolve as 3 chaves e as colunas ficam `None`; com `now - 29 dias` devolve `[]` e nada muda; `approved`/`blocked`/`pending` nunca são tocados, mesmo antigos.
  - `test_nao_apaga_o_que_algum_cadastro_usa`: arquivo referenciado e velho (48 h) permanece; arquivo sem dono e velho (48 h) é apagado; arquivo sem dono com 23 h permanece.
  - `test_erro_ao_apagar_um_arquivo_nao_impede_os_outros`: `store.delete` levanta `OSError` para a primeira chave → `delete_unreferenced` ainda apaga a segunda e devolve 1.
  - Agendador: `run_daily_purge` roda uma vez por dia (segunda chamada → `None`), apaga o órfão velho e as fotos do recusado antigo **depois** do commit (a coluna já está nula quando o arquivo some), e se `release_rejected_photos` levantar erro o dia não é marcado.
- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/services/test_document_cleanup.py tests/infra tests/api/test_scheduler.py -q`.
- [ ] **Step 3: Implementar.** `LocalDocumentStore.list_all` percorre `root/*/*` ignorando `.part` e nomes que não casam com `_KEY`; `delete` usa `_path` (que já recusa chave inválida) e `missing_ok`. `run_daily_purge`: dentro de `runtime.run` chama `release_rejected_photos` e `referenced_keys`; **depois** do commit apaga as chaves liberadas e chama `delete_unreferenced(runtime.documents, referenced, now)`; arquivos liberados que falharem ao apagar viram órfãos e saem na rodada de 24 h.
- [ ] **Step 4: Rodar** os mesmos testes → PASS.
- [ ] **Step 5: Commit** — `feat(servidor): limpeza diária das fotos de documentos sem uso (LGPD)`

---

### Task 5: Painel e contrato da API

**Files:**
- Modify: `server/painel/painel.js`, `docs/api-v1.md`
- Test: `server/tests/api/test_painel_site.py`

- [ ] **Step 1: Escrever o teste que falha** — em `test_painel_site.py`, o JavaScript servido contém `previous_rejection` e `raised_by`; e `node --check server/painel/painel.js` passa (pular o teste se `node` não existir).
- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/api/test_painel_site.py -q`.
- [ ] **Step 3: Implementar.** Tela "Cadastros": na coluna "Situação", pendente com `resubmissions > 0` mostra `pending · reenvio nº N (recusado antes: <previous_rejection>)`, tudo passando por `esc()`. Tela "Alertas": coluna "Tipo" mostra `sos · pelo motoqueiro` quando `raised_by === "rider"`. `docs/api-v1.md`: rota do SOS do motoqueiro, `raised_by` nos alertas e no evento `sos`, `resubmissions`/`previous_rejection` em `GET /v1/admin/riders`, ação `rider.auto_unblock` no registro.
- [ ] **Step 4: Rodar** `pytest tests/api/test_painel_site.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(painel): reenvio com motivo anterior, SOS do motoqueiro e contrato atualizado`

---

### Task 6: App do motoqueiro — botão de SOS

**Files:**
- Modify: `mobile/packages/corrida_core/lib/src/rider_api.dart`, `.../models/rider.dart`, `mobile/apps/rider/lib/rider_controller.dart`, `mobile/apps/rider/lib/app.dart`, `mobile/apps/rider/lib/screens/ride_screen.dart`, `mobile/packages/corrida_core/test_contract/contract_test.dart` (+ `key_audit.dart` se preciso)
- Test: `mobile/packages/corrida_core/test/rider_models_test.dart`, `.../rider_api_test.dart`, `mobile/apps/rider/test/screens/ride_screen_test.dart`, `mobile/apps/rider/test/rider_controller_test.dart`

**Interfaces:**
- Consumes: `POST /v1/rider/rides/{id}/sos` (Task 3).
- Produces: `RiderSosResult(alertId: int, repeated: bool, emergencyNumber: String)` com `fromJson` tolerante (padrão `'190'`); `RiderApi.sos(String rideId) -> Future<RiderSosResult>`; `RiderController.sos(String rideId) -> Future<RiderSosResult>`; `RideScreen(onSos: Future<RiderSosResult> Function())` obrigatório.

- [ ] **Step 1: Escrever os testes que falham.** Modelo: `fromJson({'alert_id': 7, 'repeated': true, 'emergency_number': '190'})` e o tolerante com `{}`. API: `sos('r-1')` faz `POST /v1/rider/rides/r-1/sos`. Tela: tocar em "SOS" chama `onSos` uma vez e mostra "Pedido de socorro enviado. Ligue 190 agora." (repetido: "Você já pediu socorro agora há pouco. Se precisar, ligue 190."); erro de rede mostra a mensagem amigável e **não** diz que foi enviado; o botão aparece em todas as fases da corrida (a caminho, no ponto, em andamento).
- [ ] **Step 2: Rodar e ver falhar** — `cd mobile/packages/corrida_core && dart test`; `cd mobile/apps/rider && flutter test`.
- [ ] **Step 3: Implementar.** Botão `OutlinedButton` "SOS" na `RideScreen` do motoqueiro (sem janela de confirmação, igual ao do passageiro); a navegação em `app.dart` liga `onSos: () => _controller.sos(ride.rideId)`. Estender `contract_test.dart` para chamar o SOS do motoqueiro numa corrida em andamento e a auditoria de chaves cobrir `alert_id`, `repeated`, `emergency_number`.
- [ ] **Step 4: Rodar** `dart test` em `corrida_core`, `flutter test` em `corrida_ui`, `passenger` e `rider`, `flutter analyze` nos quatro, e `mobile/tool/contrato.sh` → tudo verde.
- [ ] **Step 5: Commit** — `feat(mobile): SOS no app do motoqueiro`

---

### Task 7: Verificação final, revisão e entrega

- [ ] **Step 1:** `cd server && .venv/bin/pytest -q` (suíte inteira, inclui o simulador) → verde. Anotar a contagem.
- [ ] **Step 2:** `cd server && .venv/bin/python -m simulator demo --fast` → veredito aprovado (nada do simulador mudou de rota).
- [ ] **Step 3:** Revisão independente do ramo inteiro (agente separado, modelo mais capaz); corrigir Critical/Important com teste vermelho→verde; menores vão para o roteiro.
- [ ] **Step 4:** Atualizar o roteiro: linha "4F — feito" na tabela, seção "Itens que sobraram do plano 4F" (incluindo: o app ainda **não liga** para o 190, só mostra o aviso; o motoqueiro não tem contato de emergência; prazos de retenção para o advogado) e tirar dos "Ainda adiados" o que foi resolvido.
- [ ] **Step 5:** Mesclar no `main` localmente, rodar a suíte no resultado, enviar ao GitHub (permissão já dada pelo Levy, sem force-push), apagar o ramo.
