# Robustez do servidor (plano 4H) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, escolha do Levy) para implementar este plano tarefa a tarefa. Os passos usam caixas `- [ ]`.

**Goal:** fechar as pontas soltas pequenas do servidor que sobraram das revisões dos planos 2C, 4C, 4D e 4F e que não dependem do Levy nem do plano 7.

**Architecture:** correções cirúrgicas nos serviços existentes (cada uma com um teste vermelho primeiro) e uma migração só de índices (0012). Nada muda no contrato da API, exceto o motoqueiro passar a receber o aviso `queue_released`.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, pytest.

**Spec:** não há documento de desenho; os itens vêm da seção "Itens que sobraram" do roteiro (`2026-10-08-00-roteiro-dos-planos.md`) e foram conferidos no código. O Levy mandou (06/11/2026) "fazer no automático o app inteiro", então as decisões abaixo são minhas e ficam listadas no roteiro.

## Global Constraints

- Serviços não fazem `commit`; recebem `now`; avisos vão para o `EventCollector`. Ordem de travas: corrida, corrida da fila, motoqueiro, cobrança, passageiro.
- Português claro nas mensagens para a pessoa; nenhuma regra de dinheiro muda.
- Cada correção: teste vermelho (visto falhar pelo motivo certo) → código → verde.

## Review Focus

- Dois toques de SOS ao mesmo tempo (duas conexões reais) devem dar um alerta só, para passageiro e para motoqueiro.
- Bloquear quem já está bloqueado não pode gravar outra linha no registro do administrador nem trocar o motivo guardado.
- A limpeza de envios pela metade não pode apagar um envio que ainda está sendo gravado (só os parados há mais de 1 hora).
- Migração 0012 sobe e desce sem erro e não muda nenhuma tabela além dos índices.

---

### Task 1: O motoqueiro também é avisado quando a corrida da fila é liberada

**Files:** Modify `server/app/services/sweeps.py` (função `queue`), `docs/api-v1.md` (tabela de avisos); Test `server/tests/services/test_sweeps.py`.

**Interfaces:** o aviso `queue_released` (`ride_id, refunded`) passa a ser entregue também ao motoqueiro dono da corrida da fila (hoje só ao passageiro). O app já relê o `state` em qualquer aviso.

- [ ] **Step 1 (RED):** em `test_sweeps.py`, `test_fila_liberada_por_tempo_avisa_o_motoqueiro_tambem`: monta a mesma cena de `test_fila_que_passa_de_8_minutos_volta_para_a_busca_com_outra_moto`, roda a varredura em `AGORA + 101 + 480` e confere que `r1` (dono da corrida da fila) recebeu `queue_released` com `ride_id == "ride-1"`, além do passageiro `p1`.
- [ ] **Step 2:** rodar o teste. Expected: FAIL (r1 sem o aviso).
- [ ] **Step 3:** em `queue(...)`, guardar `rider_id = ride.rider_id` **antes** de `release_queued_ride` (ela pode limpar o dono) e, se houver, `self.events.add(rider_id, "queue_released", {"ride_id": ride_id, "refunded": refunded})`.
- [ ] **Step 4:** teste + `tests/services/test_sweeps.py` inteiro. Expected: PASS.
- [ ] **Step 5:** atualizar a linha de `queue_released` em `docs/api-v1.md` (destinatários: passageiro e motoqueiro). Commit `fix(servidor): o motoqueiro também é avisado quando a corrida da fila é liberada por tempo`.

### Task 2: `block()` recusa quem já está bloqueado

**Files:** Modify `server/app/services/riders.py` (`block`); Test `server/tests/services/test_riders.py` e uma rota em `server/tests/api/test_admin_panel_write.py`.

**Interfaces:** `RiderService.block(session, rider_id, reason)` levanta `InvalidState("o cadastro já está bloqueado")` se `profile.status == "blocked"` (a API responde 409 `invalid_state`). Nenhuma outra situação muda (pendente, recusado e aprovado continuam podendo ser bloqueados).

- [ ] **Step 1 (RED):** serviço: bloquear duas vezes levanta `InvalidState` e o motivo da primeira vez continua guardado; rota: o segundo `POST` de bloqueio dá 409 e o registro do administrador tem **uma** linha `rider.block` só.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** guarda no começo de `block`.
- [ ] **Step 4:** `pytest tests/services/test_riders.py tests/api/test_admin_panel_write.py -q`. Expected: PASS (inclusive os testes antigos de bloqueio).
- [ ] **Step 5:** commit `fix(servidor): bloquear quem já está bloqueado dá 409 em vez de gravar outra linha`.

### Task 3: SOS em dois toques ao mesmo tempo cria um alerta só

**Files:** Modify `server/app/services/safety.py` (`sos`, `rider_sos`); Test `server/tests/services/test_concorrencia.py`.

**Interfaces:** `sos` e `rider_sos` leem a corrida com `repo.get_ride(session, ride_id, for_update=True)` (a corrida é a primeira trava da ordem), de modo que o segundo pedido espera o commit do primeiro e então encontra o alerta anterior.

- [ ] **Step 1 (RED):** em `test_concorrencia.py`, parametrizado por `quem in ("passageiro", "motoqueiro")`: grava (commit) passageiro, motoqueiro, administrador e uma corrida em andamento; a thread A chama o SOS e **espera sem dar commit**; a thread B chama o SOS depois; o teste solta o commit de A meio segundo depois. Conferir exatamente 1 linha em `safety_alerts` com `kind="sos"` e que o resultado de B é `repeated=True` (passageiro) / mesmo `alert_id` (motoqueiro). Limpeza das tabelas no fim, como nos outros testes do arquivo.
- [ ] **Step 2:** rodar. Expected: FAIL (2 alertas).
- [ ] **Step 3:** trocar a leitura da corrida nos dois métodos por `for_update=True`.
- [ ] **Step 4:** teste novo + `tests/services/test_safety.py` + `tests/services/test_ordem_de_travas.py`. Expected: PASS.
- [ ] **Step 5:** commit `fix(servidor): SOS em dois toques ao mesmo tempo cria um alerta só`.

### Task 4: Limpeza dos envios pela metade (`.part`)

**Files:** Modify `server/app/infra/documents.py` (`DocumentStore.delete_stale_partials`, `LocalDocumentStore`), `server/app/services/document_cleanup.py`, e os falsos de `DocumentStore` nos testes se houver; Test `server/tests/infra/test_documents.py`, `server/tests/services/test_document_cleanup.py`.

**Interfaces:** `DocumentStore.delete_stale_partials(now: float, older_than_s: float = 3600.0) -> int` apaga os arquivos `*.part` das pastas dos donos cujo `mtime <= now - older_than_s` e devolve quantos apagou (não toca em nada que não seja `*.part` dentro de uma pasta de dono válida; pasta inexistente → 0). `purge_documents` chama o método e soma ao relatório (`partials_deleted`).

- [ ] **Step 1 (RED):** `test_documents.py`: um `.part` velho (mtime 2 h atrás) é apagado, um recente (10 min) fica, um arquivo `notas.txt` e uma foto boa ficam; `test_document_cleanup.py`: o relatório diário traz `partials_deleted`.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** implementar. Erro de disco num arquivo não impede os outros.
- [ ] **Step 4:** `pytest tests/infra/test_documents.py tests/services/test_document_cleanup.py tests/api/test_scheduler.py -q`. Expected: PASS.
- [ ] **Step 5:** commit `fix(servidor): a limpeza diária apaga os envios de foto pela metade`.

### Task 5: Índices que faltam (migração 0012)

**Files:** Create `server/migrations/versions/0012_indices_4h.py`; Modify `server/app/db/models.py` (`RideRow.__table_args__`, `RideEventRow`); Test `server/tests/db/test_schema_4h.py`.

**Interfaces:** índices `ix_rides_created_at` em `rides(created_at)` (listas do painel) e `ix_ride_events_kind_ride` em `ride_events(kind, ride_id)` (varredura de "sem sinal", a cada 3 s). A migração só cria/derruba índices.

- [ ] **Step 1 (RED):** `test_schema_4h.py`: no esquema de teste (migrações aplicadas), `pg_indexes` lista os dois índices com as colunas esperadas.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** modelos + migração `0012` (revisão anterior `0011`), `downgrade` derruba os dois.
- [ ] **Step 4:** `pytest tests/db -q` (inclui `test_migracoes_reversiveis`). Expected: PASS. Conferir `alembic upgrade head` no banco de desenvolvimento e `alembic current` = `0012`.
- [ ] **Step 5:** commit `perf(servidor): índices de rides.created_at e ride_events(kind, ride_id)`.

### Task 6: Fechamento do lote

- [ ] Suíte completa do servidor (uma vez, sozinha; olhar `free -m` antes), roteiro (seção "Itens que sobraram do plano 4H" com decisões minhas e o que ficou de fora), autorrevisão, mesclar com fast-forward na `main`, empurrar sem `--force`, apagar a branch e o registro.

## Fica de fora de propósito (vai para o roteiro)

- WebSocket continua aberto depois de logout/bloqueio: só entrega os avisos do próprio usuário; severidade baixa; mexer no código de reconexão dos apps tem risco maior que o ganho.
- `ValueError` genérico devolvendo texto interno: os serviços levantam `ValueError` com frase pronta para a pessoa em vários lugares; trocar sem lista completa quebraria mensagens. Precisa de um levantamento próprio.
- "cheguei" sem conferir distância: regra do GPS no plano 7 (o simulador anda por teletransporte).
- Oferta pendente sobrevive ao bloqueio por dívida, duas cobranças Pix abertas da dívida, `go_online` sem trava: dependem de decisão de regra do Levy sobre dívida.
- Cobrança de entrada pendente "não reaparece" no estado do motoqueiro: já é idempotente (`start_entry_charge` devolve a cobrança aberta); só falta o app pedir de novo ao reabrir.
