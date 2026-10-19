# Cancelamento tardio e saldo do passageiro — Plano de implementação (plano 4B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar a regra do Levy para o cancelamento tardio em código: janela grátis de 5 minutos contada do aceite, depois uma taxa de R$ 3 a R$ 5 conforme a distância que a moto já andou, cobrada do **saldo do passageiro** (novo), da **devolução do Pix** ou como **pendência** que bloqueia novos pedidos até ser paga, com **recurso** do passageiro decidido pelo administrador.

**Architecture:** Regras puras em `app/domain` (valor da taxa, plano de cobrança, saldo), lançamentos novos no livro-caixa (conta `balance:<passageiro>`), uma tabela `cancel_fees` com tudo o que aconteceu com cada taxa, e dois serviços: `PaymentService` cobra a taxa ao cancelar e trata os avisos de Pix novos (taxa paga, recarga); `PassengerMoneyService` faz o que a pessoa pede (pagar a pendência, recarregar, recorrer) e o que o administrador decide. Nada de dinheiro de verdade: o provedor continua falso até o plano 7.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (PostgreSQL), Redis, pytest. Nenhuma biblioteca nova.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seção 5.3 cancelamento, 7.2 a 7.6 pagamento e livro-caixa, 7.5 saldo recarregável). As decisões do Levy estão em `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`, seção "Decisões já tomadas" (18 e 19/10/2026). Este é o plano 4B; a ordem combinada com o Levy é 4B, 4C (sem sinal), 4D (bloqueio por dívida) e por último 4A (painel). Parte do estado de `main` no commit `c724a6f` (757 testes).

## Global Constraints

- Dinheiro em **centavos inteiros**; tempos em segundos; textos para a pessoa em português do Brasil, simples. Comentários e docstrings em português; nomes de código em inglês, como no resto do projeto.
- Janela grátis de cancelamento: **300 s a partir do aceite da moto** (`rides.en_route_since`). Taxa: **R$ 3,00 a R$ 5,00** (300 a 500 centavos). Os dois valores são parâmetros do banco (`app_config`, chave `rides`).
- A taxa **vai inteira para o motoqueiro** (sem parte da empresa).
- Ordem de cobrança, sempre esta: **1) saldo do passageiro, 2) retenção da devolução do Pix já pago, 3) pendência** (`passenger_profiles.unpaid_cents`, que já bloqueia novos pedidos).
- Ordem de travas no banco: corrida, motoqueiro, cobrança, **passageiro por último, depois a linha da taxa** (`cancel_fees`). Nenhum serviço faz `commit`.
- O livro-caixa continua só acrescentando: cada `ref` soma zero (`PgLedger.is_balanced()`). Conta nova: `balance:<id do passageiro>` (positiva = dinheiro do passageiro guardado no app).
- Recarga de saldo **desligada por padrão** (`balance.topup_enabled = false`): saldo recarregável depende da resposta do advogado (spec, seção 7.5). Ligada só em testes e no simulador.
- `APP_MODE=dev` continua obrigatório; nada de provedor, WhatsApp ou mapa de verdade.
- Os testes usam o Redis banco 15; o simulador usa 14 (testes do simulador, 13). `systemctl is-active postgresql redis-server` deve responder `active` duas vezes. Todos os comandos partem da pasta `server/`.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Um comando de git por vez.

## Review Focus

1. **Taxa nunca cobrada duas vezes nem esquecida:** cancelar e o aviso de Pix chegar ao mesmo tempo, aviso repetido, pagar a pendência duas vezes, recurso aceito depois de a pendência ser paga por Pix. Testes: Tarefa 6 (`test_aviso_repetido_da_taxa_nao_paga_duas_vezes`, `test_taxa_paga_depois_de_perdoada_volta_para_o_passageiro`), Tarefa 7 (`test_recurso_aceito_com_pendencia_perdoa_e_desbloqueia`).
2. **Saldo nunca negativo e sempre igual ao livro-caixa:** duas operações no mesmo saldo (taxa e recarga), devolução que não chega, recurso aceito. Testes: Tarefa 2 (`test_gastar_do_saldo_nunca_passa_do_que_tem`), Tarefa 3 (`test_saldo_negativo_e_recusado_pelo_banco`), Tarefa 8 (`test_conferencia_acusa_saldo_diferente_do_livro`).
3. **Borda do preço:** corrida de R$ 5,00 (o piso) com taxa de R$ 5,00: devolução zero, nenhuma chamada ao provedor, livro fecha. Tarefa 5 (`test_taxa_igual_ao_preco_nao_chama_o_provedor_e_o_livro_fecha`).
4. **Sem posição da moto ou posição velha:** não pode dar erro nem cobrar o máximo; cobra o mínimo. Corrida da fila que começa a andar depois. Tarefas 1 e 5 (`test_sem_posicao_cobra_o_minimo`, `test_corrida_da_fila_comeca_a_aproximacao_ao_ser_promovida`).
5. **Quem pode o quê:** recurso só do dono da taxa, uma vez, dentro de 7 dias; decisão só de administrador e só de recurso aberto; recarga desligada devolve erro claro. Tarefas 7 e 8.

## Decisões deste plano (o Levy confere)

A spec e o Levy não fecharam estes pontos; cada um custa pouco para trocar:

1. **Valor da taxa (regra provisória, o Levy disse que "depois vai ter um algoritmo de distância"):** cresce em linha reta de R$ 3,00 (moto acabou de aceitar) a R$ 5,00 (moto no ponto), em passos de R$ 0,10. Moto já no ponto de embarque (estado "chegou") paga sempre R$ 5,00. Sem posição da moto: R$ 3,00 (na dúvida, a favor do passageiro). A distância é em linha reta, medida da posição da moto no aceite até o ponto. Tudo isso fica numa função só (`late_cancel_fee_cents`) para ser trocada.
2. **Passageiro que não aparece** (espera de 5 minutos na chegada, que já cancelava sozinha): paga a taxa máxima, R$ 5,00, pelo mesmo caminho de cobrança.
3. **Saldo só paga a taxa de cancelamento.** Pagar corrida com saldo, sacar o saldo e transferir não entram (o Levy não pediu e pesam mais na dúvida do advogado).
4. **Recurso:** até 7 dias depois do cancelamento, um por taxa, com texto de 3 a 500 letras. Enquanto espera a decisão a taxa continua cobrada (e o passageiro continua bloqueado, se for pendência). **Aceito:** a pendência é perdoada e tudo o que já tinha sido cobrado volta como crédito no saldo do passageiro, pago pela empresa; o motoqueiro fica com a taxa. **Recusado:** nada muda.
5. **Devolução que não chega** (chave Pix cadastrada que não consegue receber) vira crédito no saldo, em qualquer devolução (cancelamento, Pix pago atrasado, fila desfeita). No provedor falso isso se simula com `FakePaymentProvider.undeliverable`.
6. **Pagar a pendência:** ou o saldo cobre tudo, ou o passageiro paga o valor inteiro por Pix. Não se mistura saldo com Pix numa cobrança só.
7. **Fora deste plano:** fila de recursos e lista de pendências no painel (plano 4A), aviso por notificação push, pagar corrida com saldo, saque do saldo, a conta final do "algoritmo de distância".

## File Structure

Arquivos novos (em `server/`):

| Arquivo | Responsabilidade |
|---|---|
| `app/domain/balance.py` | saldo do passageiro (`credit`, `spend_up_to`), `CancelFee`, `plan_fee_collection`, `apply_pending_payment`, `waive_pending` |
| `app/services/passenger_money.py` | `PassengerMoneyService`: pagar a pendência, recarregar, pedir e decidir recurso |
| `migrations/versions/0005_saldo_e_taxa_de_cancelamento.py` | saldo, distância inicial, cobranças de taxa e recarga, tabela `cancel_fees` |
| `tests/domain/test_late_cancel_fee.py`, `tests/domain/test_balance.py` | regras puras |
| `tests/db/test_schema_saldo.py`, `tests/db/test_repositories_saldo.py` | banco |
| `tests/services/test_refund_to_balance.py`, `test_cancel_fee.py`, `test_passenger_money.py`, `test_appeals.py` | serviços |
| `tests/api/test_cancel_fee_routes.py`, `test_balance_routes.py`, `test_admin_appeals.py` | API |

Arquivos alterados: `app/domain/config.py`, `rides.py`, `ledger.py`, `payments.py`; `app/db/models.py`, `repositories.py`, `queries.py`, `pg_ledger.py`, `config_store.py`; `app/adapters/fake_payments.py`; `app/services/payments.py`, `trips.py`, `dispatch.py`, `sweeps.py`, `quotes.py`; `app/runtime.py`; `app/api/errors.py`, `views.py`, `routes/passenger.py`, `routes/admin.py`, `routes/payments.py`, `routes/dev.py`; `simulator/*`; `docs/api-v1.md`, `docs/simulador.md`, roteiro dos planos.

---

### Task 1: Regras puras da taxa e os parâmetros novos

**Files:**
- Modify: `app/domain/config.py`, `app/domain/rides.py`, `app/db/config_store.py`
- Test: `tests/domain/test_late_cancel_fee.py` (novo), `tests/domain/test_rides.py`, `tests/domain/test_config_api.py`, `tests/db/test_config_store.py`

**Interfaces:**
- Produces:
  - `RideConfig`: `free_cancel_after_accept_s: int = 300`, `cancel_fee_min_cents: int = 300`, `cancel_fee_max_cents: int = 500`, `cancel_fee_round_cents: int = 10`, `appeal_window_s: int = 604_800`. **Sai** `cancel_compensation_cents`.
  - `BalanceConfig(topup_enabled: bool = False, topup_min_cents: int = 1000, topup_max_cents: int = 20_000)` e `AppConfig.balance: BalanceConfig = BalanceConfig()` (chave `"balance"` em `config_store`).
  - `Ride.approach_start_m: float | None = None` (distância da moto ao ponto de embarque quando começou a vir).
  - `approach_progress(start_m: float | None, now_m: float | None) -> float | None`
  - `late_cancel_fee_cents(progress: float | None, cfg: RideConfig = _DEFAULT) -> int`
  - `CancelResult(fee_cents: int, refund_needed: bool)` (o campo `compensation_cents` vira `fee_cents`, mesma posição)
  - `cancel(ride, now, cfg=_DEFAULT, progress: float | None = None) -> CancelResult`

- [ ] **Step 1: Testes que falham** em `tests/domain/test_late_cancel_fee.py`:

```python
@pytest.mark.parametrize("progress, esperado", [(0.0, 300), (1.0, 500), (0.5, 400), (0.33, 370), (0.75, 450), (None, 300)])
def test_taxa_cresce_com_a_distancia_andada(progress, esperado):
    assert late_cancel_fee_cents(progress) == esperado

def test_taxa_respeita_os_limites_mesmo_com_progresso_fora_da_faixa():
    assert late_cancel_fee_cents(-0.4) == 300 and late_cancel_fee_cents(7.0) == 500

@pytest.mark.parametrize("inicio, agora, esperado", [(2000, 500, 0.75), (2000, 2500, 0.0), (2000, 0, 1.0), (40, 40, 1.0), (None, 300, None), (2000, None, None)])
def test_progresso_da_aproximacao(inicio, agora, esperado):
    assert approach_progress(inicio, agora) == esperado

def test_sem_posicao_cobra_o_minimo():   # moto sem posição conhecida: progress None
    ride = _aceita(en_route_since=1000.0)
    assert cancel(ride, 1301.0, progress=None) == CancelResult(300, False)
```

Em `tests/domain/test_rides.py` ajustar/acrescentar: dentro da janela (`now - en_route_since == 300`) taxa 0; um segundo depois, taxa conforme o progresso (`CancelResult(450, False)` com `progress=0.75`); estado `ARRIVED` depois da janela cobra 500 com qualquer `progress`; `QUEUED`/`SEARCHING` sempre 0; `cancel_after_arrival_timeout` devolve `CancelResult(500, refund_needed)`. Em `tests/db/test_config_store.py`: `load_config(session, "balance")` devolve o padrão; salvar `BalanceConfig(topup_enabled=True)` e ler de volta; um `rides` gravado antes com a chave antiga `cancel_compensation_cents` **ainda carrega** (a chave desconhecida é ignorada, a nova usa o padrão). `validate`: mínimo maior que o máximo da taxa é recusado ao salvar.

- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/domain/test_late_cancel_fee.py tests/domain/test_rides.py tests/db/test_config_store.py -q` → falha por nomes que não existem.
- [ ] **Step 3: Implementar** em `rides.py` as duas funções (`approach_progress`: `None` se faltar dado; `1.0` se `start_m <= 50`; senão `clamp(1 - now_m/start_m, 0, 1)`. `late_cancel_fee_cents`: `None` → mínimo; senão mínimo + (máximo − mínimo) × progresso limitado a [0, 1], arredondado ao múltiplo mais perto de `cancel_fee_round_cents`) e o novo `cancel`: depois da janela (`now - en_route_since > free_cancel_after_accept_s`), estados `ACCEPTED`/`ARRIVED`, a taxa é `late_cancel_fee_cents(1.0 if estado é ARRIVED else progress, cfg)`; `cancel_after_arrival_timeout` usa progresso 1.0. Docstring de `late_cancel_fee_cents`: "REGRA PROVISÓRIA: o Levy vai trocar por um algoritmo de distância". Em `config_store.py`: registrar `"balance": BalanceConfig`, incluir `balance` em `AppConfig`/`load_app_config`, filtrar chaves desconhecidas em `_from_json` (só as que são campos da classe) e validar `cancel_fee_min_cents <= cancel_fee_max_cents` (e ambos > 0, `cancel_fee_round_cents > 0`) ao salvar `rides`.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando, mais `tests/domain tests/db/test_config_store.py -q` inteiros.
- [ ] **Step 5: Commit**

```bash
git add app/domain/config.py app/domain/rides.py app/db/config_store.py tests/domain tests/db/test_config_store.py
git commit -m "feat(rules): taxa de cancelamento tardio de R\$ 3 a R\$ 5 pela distância andada e janela de 5 minutos"
```

---

### Task 2: Saldo e taxa no domínio e no livro-caixa

**Files:**
- Create: `app/domain/balance.py`
- Modify: `app/domain/rides.py` (`PassengerAccount.balance_cents`), `app/domain/ledger.py`, `app/db/pg_ledger.py`
- Test: `tests/domain/test_balance.py` (novo), `tests/domain/test_ledger.py`, `tests/db/test_pg_ledger.py`

**Interfaces:**
- Produces em `app/domain/balance.py`:
  - `credit(acc: PassengerAccount, cents: int) -> None`; `spend_up_to(acc, cents) -> int` (devolve quanto saiu; nunca passa do saldo)
  - `@dataclass FeePlan(from_balance: int, retained: int, pending: int)` e `plan_fee_collection(fee_cents: int, balance_cents: int, held_cents: int) -> FeePlan` (`from_balance = min(saldo, taxa)`; `retained = min(resto, held)`; `pending = resto − retained`)
  - `@dataclass CancelFee`: `ride_id, passenger_id, rider_id: str`, `fee_cents: int`, `reason: str` ("passenger" | "arrival_timeout"), `created_at: float`, `progress: float | None = None`, `from_balance_cents = 0`, `retained_cents = 0`, `pending_cents = 0`, `paid_later_cents = 0`, `waived_cents = 0`, `credited_back_cents = 0`, `appeal_state = "none"`, `appeal_text: str | None = None`, `appealed_at/decided_at: float | None = None`, `decided_by: str | None = None`, `decision_note: str | None = None`
  - `apply_pending_payment(fee: CancelFee, cents: int) -> None`; `waive_pending(fee: CancelFee) -> int` (zera a pendência, soma em `waived_cents`, devolve o valor perdoado)
- Produces em `Ledger`/`PgLedger` (mesmas assinaturas nos dois; `PgLedger` carrega os lançamentos do `ref`, deixa o domínio validar e grava só os novos):
  - `EntryKind.BALANCE_CREDIT = "balance_credit"`, `BALANCE_SPEND = "balance_spend"`, `TOPUP = "topup"`; `Ledger.balance_account(passenger_id) -> str` (`"balance:<id>"`)
  - `post_refund(charge_id, *, keep_cents=0)` — **estende** o atual: provedor recebe `preço − keep_cents`, empresa estorna sua parte, o motoqueiro fica com `keep_cents` (lança `keep_cents − valor original`)
  - `post_refund_to_balance(charge_id, passenger_id, *, keep_cents=0)` — igual, mas o `preço − keep_cents` vai para `balance:<passageiro>` (tipo `BALANCE_CREDIT`)
  - `post_spend_balance(ref, passenger_id, rider_id, amount_cents)` — `balance:` −valor, `rider:` +valor (`BALANCE_SPEND`)
  - `post_topup(charge_id, passenger_id, amount_cents)` — provedor −valor, `balance:` +valor (`TOPUP`)
  - `post_credit_from_company(ref, passenger_id, amount_cents)` — empresa −valor, `balance:` +valor (`BALANCE_CREDIT`), usado no recurso aceito

- [ ] **Step 1: Testes que falham.** `tests/domain/test_balance.py`: `test_gastar_do_saldo_nunca_passa_do_que_tem` (saldo 100, `spend_up_to(acc, 400) == 100`, saldo 0); `test_credito_negativo_ou_zero_e_recusado`; tabela de `plan_fee_collection` com os casos (saldo, taxa, retido pelo Pix) → `FeePlan`: `(1000, 400, 0) → (400, 0, 0)`, `(100, 400, 0) → (100, 0, 300)`, `(0, 400, 700) → (0, 400, 0)`, `(150, 400, 700) → (150, 250, 0)`, `(0, 500, 500) → (0, 500, 0)`, `(0, 400, 0) → (0, 0, 400)`; `test_perdoar_a_pendencia_zera_e_soma_nos_perdoados`; `apply_pending_payment` passa de pendente para pago depois e recusa valor maior que a pendência. `tests/domain/test_ledger.py`: devolução parcial com `keep_cents=400` de uma cobrança de 700 (motoqueiro 600, empresa 100) deixa `balance("rider:r1") == 400`, `balance(COMPANY) == 0`, `balance(PROVIDER) == -400`, `is_balanced()`; `keep_cents=700` não cria lançamento do provedor com valor e fecha; `post_refund_to_balance` com `keep_cents=400` deixa `balance("balance:p1") == 300` e fecha; devolver duas vezes (qualquer combinação de `post_refund`/`post_refund_to_balance`) levanta `ValueError`; `post_spend_balance`, `post_topup` e `post_credit_from_company` fecham e recusam valor ≤ 0; `keep_cents` negativo ou maior que o preço é recusado. `tests/db/test_pg_ledger.py`: o mesmo cenário da devolução parcial pelo `PgLedger` e uma chamada repetida levanta erro sem gravar nada.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/domain/test_balance.py tests/domain/test_ledger.py tests/db/test_pg_ledger.py -q` → falha.
- [ ] **Step 3: Implementar** `balance.py`, o campo `balance_cents: int = 0` em `PassengerAccount` e os lançamentos novos em `Ledger` (generalizar o corpo de `post_refund` num auxiliar `_reverse(charge_id, destination_account, kind, keep_cents)`: conta do provedor/saldo recebe `preço − keep`, conta `company` estorna o valor original, conta `rider:*` lança `keep − valor original`; o guarda de repetição olha `REFUND` **e** `BALANCE_CREDIT` do mesmo `ref`) e os espelhos em `PgLedger` (mesmo padrão de `_load`/`_store_new`).
- [ ] **Step 4: Rodar e ver passar** os três arquivos, mais `tests/domain tests/db/test_pg_ledger.py -q`.
- [ ] **Step 5: Commit**

```bash
git add app/domain app/db/pg_ledger.py tests/domain tests/db/test_pg_ledger.py
git commit -m "feat(rules): saldo do passageiro, plano de cobrança da taxa e lançamentos novos do livro-caixa"
```

---

### Task 3: Banco: migração 0005, modelos e repositórios

**Files:**
- Create: `migrations/versions/0005_saldo_e_taxa_de_cancelamento.py`
- Modify: `app/db/models.py`, `app/db/repositories.py`, `app/db/queries.py`, `app/domain/payments.py` (campos do `PixCharge`)
- Test: `tests/db/test_schema_saldo.py`, `tests/db/test_repositories_saldo.py` (novos), `tests/db/test_migracoes_reversiveis.py` (conferir `0004` ↔ topo), os testes de esquema existentes (modelos × migrações) devem continuar passando

**Interfaces:**
- Produces (banco): `passenger_profiles.balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0)` (`passenger_balance_non_negative`); `rides.approach_start_m DOUBLE PRECISION NULL`; `pix_charges.passenger_id VARCHAR(36) NULL REFERENCES users`, `pix_charges.rider_id` passa a aceitar NULL; `purpose IN ('ride','end','entry','fee','topup')`; `charge_ride_required`: `purpose IN ('entry','topup') OR ride_id IS NOT NULL`; `charge_owner`: `(purpose = 'topup' AND passenger_id IS NOT NULL AND rider_id IS NULL) OR (purpose <> 'topup' AND rider_id IS NOT NULL)`; tabela `cancel_fees` (`ride_id` chave primária e FK de `rides`; `passenger_id`, `rider_id` FK de `users`; `fee_cents` > 0; `reason`; `progress`; `from_balance_cents`, `retained_cents`, `pending_cents`, `paid_later_cents`, `waived_cents`, `credited_back_cents` todos ≥ 0 e **`from_balance_cents + retained_cents + pending_cents + paid_later_cents + waived_cents = fee_cents`** (`fee_parts_close`); `appeal_state IN ('none','open','accepted','rejected')`; `appeal_text` (500), `appealed_at`, `decided_at`, `decided_by` FK `users`, `decision_note` (200); `created_at`); índices `ix_cancel_fees_passenger (passenger_id)` e `ix_cancel_fees_appeal (appeal_state)`.
- Produces (código): `PixCharge.passenger_id: str = ""` e `PixCharge.refunded_cents: int = 0` (este só existe no objeto do provedor falso, não vai para o banco); em `repositories`: `get_passenger_account`/`save_passenger_account` passam a levar `balance_cents`; `_ride_to_domain`/`_apply_ride` levam `approach_start_m`; `_charge_to_domain`/`_apply_charge` levam `passenger_id` (`""` ↔ NULL, como `ride_id`) e `rider_id` vazio ↔ NULL;
  - `add_cancel_fee(session, fee: CancelFee) -> None`, `get_cancel_fee(session, ride_id, *, for_update=False) -> CancelFee` (`LookupError` se não existe), `save_cancel_fee(session, fee) -> None`
  - `pending_cancel_fee(session, passenger_id, *, for_update=False) -> CancelFee | None` (a de `pending_cents > 0` mais antiga)
  - `recent_cancel_fees(session, passenger_id, since: float) -> list[CancelFee]` (mais nova primeiro)
  - `find_open_charge(session, ride_id: str, purpose: str) -> PixCharge | None` (não paga, não devolvida); `find_open_topup_charge(session, passenger_id) -> PixCharge | None`
  - em `queries`: `@dataclass AppealItem(ride_id, passenger_id, passenger_name, rider_name, fee_cents, reason, created_at, appeal_state, appeal_text, appealed_at, decided_at, decision_note)`, `list_appeals(session, status: str, limit: int, offset: int) -> list[AppealItem]` (mais antigo primeiro), `passenger_balances_total(session) -> int`, `ledger_balances_total(session) -> int` (soma das contas `balance:%`), `inconsistent_fee_ids(session) -> list[str]` (taxas em que `from_balance + retained + paid_later + waived + pending ≠ fee`; com a restrição do banco deve ser sempre vazio, a consulta existe para a conferência do simulador)

- [ ] **Step 1: Testes que falham.** `test_schema_saldo.py`: `test_saldo_negativo_e_recusado_pelo_banco`; `test_taxa_com_partes_que_nao_fecham_e_recusada`; `test_taxa_de_cancelamento_so_aceita_situacao_de_recurso_conhecida`; `test_recarga_exige_passageiro_e_nao_aceita_motoqueiro` (`purpose='topup'` com `rider_id` preenchido → erro; sem `passenger_id` → erro); `test_cobranca_de_taxa_exige_corrida`. `test_repositories_saldo.py`: ida e volta de `CancelFee` (todos os campos, incluindo recurso); `pending_cancel_fee` devolve a mais antiga com pendência e ignora as já pagas; `recent_cancel_fees` respeita `since` e a ordem; saldo do passageiro vai e volta pelo repositório; cobrança `topup` (sem corrida, sem motoqueiro) vai e volta; `find_open_charge` só acha a não paga do propósito pedido; `list_appeals("open")` junta nomes de passageiro e motoqueiro.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/db -q` → falha (e `test_migracoes_reversiveis` mostra o que falta).
- [ ] **Step 3: Implementar** a migração `0005` (revisão `0005`, `down_revision = "0004"`; `upgrade` altera as tabelas e cria `cancel_fees`; `downgrade` desfaz tudo, inclusive voltar `rider_id` a NOT NULL e os `CHECK` antigos — apagando antes as cobranças `fee`/`topup`), os modelos (`CancelFeeRow` e colunas) e as funções acima. Atualizar `tests/db/test_migracoes_reversiveis.py` para também conferir `cancel_fees` no topo.
- [ ] **Step 4: Rodar e ver passar:** `.venv/bin/python -m pytest tests/db tests/domain -q`.
- [ ] **Step 5: Commit**

```bash
git add migrations app/db app/domain/payments.py tests/db
git commit -m "feat(db): saldo do passageiro, taxa de cancelamento, cobranças de taxa e recarga"
```

---

### Task 4: Provedor e devolução: Pix inteiro, parcial ou para o saldo

**Files:**
- Modify: `app/domain/payments.py`, `app/adapters/fake_payments.py`, `app/services/payments.py`
- Test: `tests/services/test_refund_to_balance.py` (novo), `tests/services/test_payment_service.py`, `tests/adapters/` (teste do provedor falso, se já existir um arquivo, senão `tests/adapters/test_fake_payments.py`)

**Interfaces:**
- Produces:
  - `class RefundUndeliverable(Exception)` em `app/domain/payments.py`: "a devolução não consegue chegar à chave Pix cadastrada".
  - `PaymentProvider.create_pix_charge(self, ride_id, rider_id, amount_cents, split, purpose="ride", passenger_id="") -> PixCharge`; `PaymentProvider.refund(self, charge_id: str, amount_cents: int | None = None) -> None` (`None` = tudo).
  - `FakePaymentProvider`: `undeliverable: set[str]` (ids de cobrança cuja devolução falha), `refund_all_undeliverable: bool = False`; `refund` parcial acumula `PixCharge.refunded_cents` e só marca `refunded=True` quando devolveu tudo; recusa valor ≤ 0 ou maior que o restante; levanta `RefundUndeliverable` antes de mexer em qualquer coisa quando a cobrança está em `undeliverable` (ou a chave global está ligada).
  - `PaymentService._refund(self, session, passenger_id: str, charge: PixCharge, acc: RiderAccount, ledger: PgLedger, *, keep_cents: int = 0) -> str` devolve `"pix"` ou `"balance"`: se `preço − keep_cents > 0`, chama `provider.refund(charge_id, preço − keep_cents)`; sucesso → `ledger.post_refund(charge_id, keep_cents=keep_cents)`; `RefundUndeliverable` → `ledger.post_refund_to_balance(...)` e `credit` no saldo do passageiro (travado e salvo na hora); com `preço − keep_cents == 0` não chama o provedor. Depois, como hoje: `charge.refunded = True` e a dívida abatida volta (`restore_charge_debt`) ou a reservada é solta (`release_charge_debt`).
  - Todos os pontos que chamavam `_refund` passam o `passenger_id` da corrida; o aviso `payment_refunded` ganha `"to": "pix" | "balance"` e `"balance_cents"` quando for para o saldo.

- [ ] **Step 1: Testes que falham.** `test_refund_to_balance.py` (usa os ajudantes de `tests/services/test_trips.py`: `aceitar`, `pagar`; copiar o `w` de lá): `test_devolucao_que_nao_chega_vira_saldo` (Pix de R$ 7,00 pago, `provider.refund_all_undeliverable = True`, cancela dentro da janela → `repo.get_passenger_account(...).balance_cents == 700`, livro fecha, `PgLedger.balance("balance:p1") == 700`, `balance("rider:r1") == 0`, evento `payment_refunded` com `to == "balance"`, cobrança com `refunded == True`); `test_pix_pago_atrasado_depois_do_cancelamento_tambem_cai_no_saldo` (o caminho de `on_provider_event`); `test_fila_desfeita_com_devolucao_que_nao_chega_vira_saldo`; `test_devolucao_normal_continua_indo_para_o_pix` (`to == "pix"`, saldo 0). No provedor falso: devolução parcial acumula e recusa passar do restante; `undeliverable` não altera a cobrança. Atualizar `RefundFalha` em `test_payment_service.py` para a assinatura nova.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/services/test_refund_to_balance.py tests/services/test_payment_service.py -q` → falha.
- [ ] **Step 3: Implementar** o que está em Interfaces e ajustar os três pontos de chamada de `_refund` em `PaymentService` (`on_provider_event`, `_settle_cancellation`, `release_queued_ride`), mais `FakePaymentProvider.create_pix_charge` (grava `passenger_id`).
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services tests/api -q` (nada do que já existia pode quebrar).
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(payments): devolução parcial e devolução que não chega vira saldo do passageiro"
```

---

### Task 5: Onde a moto começou a vir e a cobrança da taxa ao cancelar

**Files:**
- Modify: `app/services/dispatch.py`, `app/services/trips.py`, `app/services/payments.py`, `app/services/sweeps.py`, `app/runtime.py`
- Test: `tests/services/test_cancel_fee.py` (novo), `tests/services/test_trips.py`, `tests/services/test_sweeps.py`, `tests/services/test_payment_service.py`

**Interfaces:**
- Consumes: Tarefas 1 a 4.
- Produces:
  - `TripService.__init__(self, payments, dispatcher, events, cfg=None, positions: PositionStore | None = None)`; `Runtime.make_unit` passa `positions`.
  - `DispatchService.accept_offer` grava `ride.approach_start_m = haversine_m(posição da moto, ponto de embarque)` quando a moto não está ocupada (se não há posição, fica `None`); `TripService.after_ride_ends` grava o mesmo na corrida da fila ao promovê-la (`promote_from_queue`).
  - `TripService.cancel_fee_preview(self, session, ride_id: str, now: float) -> int`: a taxa que valeria se o passageiro cancelasse agora (0 fora de `ACCEPTED`/`ARRIVED` ou dentro da janela).
  - `@dataclass(frozen=True) CancelOutcome(fee_cents: int, refund_needed: bool, refund_to: str | None = None, from_balance_cents: int = 0, retained_cents: int = 0, pending_cents: int = 0)` em `app/services/payments.py`.
  - `PaymentService.cancel_ride(self, session, ride_id, now, progress: float | None = None) -> CancelOutcome` e `cancel_after_arrival_timeout(self, session, ride_id, now) -> CancelOutcome`. `TripService.cancel_by_passenger(...) -> CancelOutcome`.
  - Cobrança (`PaymentService._collect_cancel_fee`, chamada por `_settle_cancellation` quando `result.fee_cents > 0`): trava o passageiro; `plan_fee_collection(taxa, saldo, preço do Pix pago ou 0)`; gasta do saldo (`post_spend_balance` com `ref = f"fee:{ride_id}:cancel"`); soma a pendência em `unpaid_cents`; devolve o Pix com `keep_cents = retained`; grava `CancelFee`. Eventos: ao passageiro `cancel_fee` `{ride_id, fee_cents, from_balance_cents, retained_cents, pending_cents, balance_cents}`; ao motoqueiro, `ride_cancelled` ganha `"fee_cents"`. O evento do histórico da corrida troca `compensation_cents` por `fee_cents`.
  - Distância atual da moto no cancelamento: `positions.get(rider_id)` até o ponto de embarque (`repo.get_ride_details(...).pickup`), `approach_progress(ride.approach_start_m, distância atual)`; sem posição → `None`.

- [ ] **Step 1: Testes que falham** (`test_cancel_fee.py`, mesmo `w` de `test_trips.py`; moto em `pt(2000, 0)` no aceite, ponto de embarque na origem; para andar, `positions.update("r1", pt(500, 0), now)`): 
  - `test_aceite_guarda_a_distancia_inicial_da_moto` (`approach_start_m` ≈ 2000 com folga de 5 m).
  - `test_corrida_da_fila_comeca_a_aproximacao_ao_ser_promovida` (usa `_com_corrida_na_fila`; ao promover, `approach_start_m` é a distância naquele instante).
  - `test_cancelar_dentro_da_janela_nao_cobra_nada` (instante `en_route_since + 300`): `fee_cents == 0`, nenhuma linha em `cancel_fees`, nenhum evento `cancel_fee`.
  - `test_taxa_sai_do_saldo` (saldo 1000, dinheiro, moto a 75% do caminho, cancela 301 s depois): taxa 450, saldo 550, `balance("rider:r1") == 450`, pendência 0, `PgLedger.is_balanced()`, linha com `from_balance_cents == 450`.
  - `test_saldo_curto_deixa_pendencia_e_bloqueia` (saldo 100, taxa 300): `unpaid_cents == 200`, `passenger_block_reason` fala da taxa (ver Tarefa 6), saldo 0.
  - `test_pix_pago_sem_saldo_retem_a_taxa_da_devolucao` (preço 700, divisão 600/100, taxa 400): `refund_to == "pix"`, `provider.charges[...].refunded_cents == 300`, `balance("rider:r1") == 400`, `balance(COMPANY) == 0`, livro fecha, dívida do motoqueiro abatida volta (como no cancelamento sem taxa).
  - `test_pix_pago_com_saldo_parcial_usa_o_saldo_primeiro` (saldo 150, taxa 400: 150 do saldo, 250 retidos, devolve 450).
  - `test_taxa_com_devolucao_que_nao_chega_retem_e_credita_o_resto` (`refund_all_undeliverable`; taxa 400, preço 700: saldo do passageiro termina em 300; `refund_to == "balance"`).
  - `test_taxa_igual_ao_preco_nao_chama_o_provedor_e_o_livro_fecha` (preço 500, taxa 500: devolução 0, `refunded_cents == 0`, `balance("rider:r1") == 500`).
  - `test_chegou_ao_ponto_cobra_o_maximo`; `test_sem_posicao_cobra_o_minimo`.
  - `test_cancelar_duas_vezes_nao_cobra_duas_vezes` (a segunda levanta `InvalidTransition` e não cria nada).
  - `test_espera_na_chegada_esgotada_cobra_o_maximo_pelo_mesmo_caminho` (no `SweepService`: evento `ride_cancelled` ao motoqueiro com `fee_cents == 500`, `cancel_fees.reason == "arrival_timeout"`).
  - `test_previa_da_taxa_acompanha_o_que_seria_cobrado` (`cancel_fee_preview` igual a `fee_cents` do cancelamento logo em seguida, e 0 dentro da janela).
  - Ajustar os testes antigos que comparavam `CancelResult(200, False)`/`compensation_cents == 200` (`test_trips.py`, `test_sweeps.py`): agora o prazo é 300 s e o valor vem da posição.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/services/test_cancel_fee.py tests/services/test_trips.py tests/services/test_sweeps.py -q` → falha.
- [ ] **Step 3: Implementar** o que está em Interfaces. A pendência soma em `passenger_profiles.unpaid_cents` (reaproveita o bloqueio de pedidos que já existe). O aviso ao passageiro (`cancel_fee`) só sai se `fee_cents > 0`. O `ride_cancelled` do `SweepService` (espera na chegada) também leva `fee_cents`.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services tests/api -q`.
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(payments): taxa de cancelamento tardio cobrada do saldo, da devolução do Pix ou como pendência"
```

---

### Task 6: Pagar a pendência e recarregar o saldo

**Files:**
- Create: `app/services/passenger_money.py`
- Modify: `app/services/payments.py` (`on_provider_event`: propósitos `fee` e `topup`), `app/services/quotes.py` (`passenger_block_reason`), `app/runtime.py` (`Unit.money`), `app/api/errors.py` (regras novas)
- Test: `tests/services/test_passenger_money.py` (novo)

**Interfaces:**
- Produces:
  - `class NothingToPay(Exception)` (409 `nothing_to_pay`, "Você não tem nada para pagar."), `class TopupDisabled(NotAllowed)` (403 `topup_disabled`, "A recarga de saldo ainda não está disponível.") em `app/services/passenger_money.py`.
  - `PassengerMoneyService(payments: PaymentService, events: EventCollector, cfg: AppConfig | None = None)`:
    - `pay_pending(self, session, passenger_id: str, now: float) -> PixCharge | None`: sem pendência → `NothingToPay`; se `saldo >= pendência`, paga tudo do saldo (`post_spend_balance` com `ref = f"fee:{ride_id}:pay"`, `apply_pending_payment`, `unpaid_cents` cai, avisos `fee_paid` e, se `unpaid_cents == 0`, `unblocked`) e devolve `None`; senão devolve a cobrança Pix aberta do propósito `fee` (ou cria uma de valor igual à pendência: `Split(rider_cents=pendência, company_cents=0, debt_paid_cents=0)`, `ride_id` da taxa, `rider_id` do motoqueiro da corrida).
    - `topup(self, session, passenger_id: str, amount_cents: int, now: float) -> PixCharge`: `TopupDisabled` se `cfg.balance.topup_enabled` é falso; `ValueError("A recarga vai de R$ 10,00 a R$ 200,00.")`-estilo (texto montado com `brl` e os limites do parâmetro) se fora de `topup_min_cents..topup_max_cents`; reaproveita a cobrança de recarga aberta de mesmo valor; senão cria (`purpose="topup"`, `passenger_id`, `Split(0, amount, 0)`).
  - `PaymentService.on_provider_event` passa a tratar `known.purpose`:
    - `"fee"` → `_on_fee_paid(session, known)`: trava a cobrança, o passageiro e a taxa (nessa ordem; não precisa travar a corrida, que já terminou). Se a taxa ainda tem `pending_cents == charge.amount_cents`: lança `post_charge_payment`, `apply_pending_payment`, `unpaid_cents −= valor`, avisos `fee_paid` / `unblocked`, devolve `"applied"`. Se a taxa foi perdoada, já foi paga ou o valor mudou: lança o pagamento e **devolve tudo** pelo `_refund` (vai ao Pix ou ao saldo), devolve `"refunded"`.
    - `"topup"` → `_on_topup_paid`: `post_topup`, `credit`, aviso `balance_changed {balance_cents}`, devolve `"applied"`; repetido → `"duplicate"`.
  - `passenger_block_reason` (em `quotes.py`): com pendência de taxa → "Falta pagar a taxa do cancelamento. Pague para pedir outra moto." (a mensagem de corrida não paga continua como está).

- [ ] **Step 1: Testes que falham** (`test_passenger_money.py`): `test_pendencia_paga_pelo_saldo_desbloqueia` (saldo recebido por uma recarga/crédito depois da pendência; `pay_pending` devolve `None`, `unpaid_cents == 0`, avisos `fee_paid` e `unblocked`); `test_pendencia_sem_saldo_gera_cobranca_pix_do_valor_inteiro` (cobrança `purpose == "fee"`, valor = pendência); `test_pedir_a_cobranca_duas_vezes_devolve_a_mesma`; `test_pagar_o_pix_da_taxa_quita_e_desbloqueia` (via `on_provider_event(provider.mark_paid(...))`; `balance("rider:r1")` ganha a taxa; livro fecha); `test_aviso_repetido_da_taxa_nao_paga_duas_vezes`; `test_taxa_paga_depois_de_perdoada_volta_para_o_passageiro` (perdoa a pendência com `waive_pending`, paga a cobrança antiga: resultado `"refunded"`, passageiro não fica com saldo a mais nem a menos do que o valor pago, livro fecha); `test_sem_pendencia_nao_ha_o_que_pagar`; `test_recarga_desligada_por_padrao_recusa_com_erro_claro`; `test_recarga_fora_dos_limites_e_recusada`; `test_recarga_paga_credita_o_saldo_e_o_livro_fecha`; `test_recarga_repetida_credita_uma_vez`.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/services/test_passenger_money.py -q` → falha.
- [ ] **Step 3: Implementar** o serviço, os dois tratamentos de aviso, a mensagem e a ligação em `Runtime.make_unit` (`Unit.money`). Cuidar da ordem de travas dita nas restrições.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services tests/api -q`.
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(payments): pagar a taxa pendente (saldo ou Pix) e recarregar o saldo, desligado por padrão"
```

---

### Task 7: Recurso da taxa

**Files:**
- Modify: `app/services/passenger_money.py`, `app/api/errors.py`
- Test: `tests/services/test_appeals.py` (novo)

**Interfaces:**
- Produces em `PassengerMoneyService`:
  - `class AppealNotAllowed(Exception)` (409 `appeal_not_allowed`, texto pronto para a pessoa).
  - `file_appeal(self, session, passenger_id: str, ride_id: str, text: str, now: float) -> None`: `LookupError` se a corrida não tem taxa; `NotYourRide` se a taxa é de outro passageiro; `AppealNotAllowed("Você já pediu a revisão desta taxa.")` se `appeal_state != "none"`; `AppealNotAllowed("O prazo para pedir revisão acabou.")` se `now − created_at > appeal_window_s`; `ValueError` se o texto (sem espaços nas pontas) tem menos de 3 ou mais de 500 letras. Marca `open`, guarda texto e hora, avisa os administradores (`appeal_opened {ride_id}`) e o histórico da corrida ganha `fee_appeal_opened`.
  - `decide_appeal(self, session, admin_id: str, ride_id: str, accept: bool, note: str, now: float) -> None`: `AppealNotAllowed("Este recurso já foi decidido.")` se não está `open`. **Aceitar:** `waive_pending` (e `unpaid_cents −= perdoado`), `credited = from_balance + retained + paid_later` ainda não devolvidos → `post_credit_from_company(f"fee:{ride_id}:appeal", ...)` e `credit` no saldo (`credited_back_cents`), estado `accepted`. **Recusar:** estado `rejected`, nada mais muda. Nos dois: `decided_at`, `decided_by`, `decision_note`, aviso ao passageiro `appeal_decided {ride_id, decision, credited_cents}` e, se a pendência foi perdoada e `unpaid_cents` chegou a 0, também `unblocked`.

- [ ] **Step 1: Testes que falham** (`test_appeals.py`): `test_recurso_abre_uma_vez_e_avisa_o_administrador`; `test_recurso_de_outra_pessoa_e_recusado` (`NotYourRide`); `test_recurso_depois_de_7_dias_e_recusado` (usa `now = created_at + 604_800 + 1`; exatamente em `604_800` ainda vale); `test_recurso_sem_taxa_e_recusado`; `test_texto_curto_ou_longo_demais_e_recusado`; `test_recurso_aceito_devolve_ao_saldo_o_que_foi_cobrado` (taxa de 400 paga: saldo 150 + retenção 250 → saldo do passageiro sobe 400, `balance(COMPANY) == -400`, livro fecha, motoqueiro continua com 400); `test_recurso_aceito_com_pendencia_perdoa_e_desbloqueia` (pendência 300 e 100 já cobrados do saldo → `unpaid_cents == 0`, crédito 100, aviso `unblocked`); `test_recurso_recusado_nao_muda_nada_de_dinheiro`; `test_decidir_duas_vezes_e_recusado`; `test_decidir_recurso_que_nao_foi_aberto_e_recusado`.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/services/test_appeals.py -q` → falha.
- [ ] **Step 3: Implementar** os dois métodos (ordem de travas: passageiro, depois a taxa; o administrador de `queries.admin_ids` já existe) e as regras de erro.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services -q`.
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(payments): recurso da taxa de cancelamento, pedido pelo passageiro e decidido pelo administrador"
```

---

### Task 8: API, conferência do servidor e contrato

**Files:**
- Modify: `app/api/views.py`, `app/api/routes/passenger.py`, `app/api/routes/admin.py`, `app/api/routes/payments.py` (`GET /v1/charges/{id}`: a recarga pertence ao passageiro), `app/api/routes/dev.py`, `docs/api-v1.md`
- Test: `tests/api/test_cancel_fee_routes.py`, `tests/api/test_balance_routes.py`, `tests/api/test_admin_appeals.py` (novos), `tests/api/test_passenger_routes.py`, `tests/api/test_dev_audit.py`

**Interfaces:**
- Produces (todas com o formato de erro de sempre):
  - `POST /v1/passenger/rides/{ride_id}/cancel` → `{"refund": bool, "fee_cents": int, "fee": null | {"from_balance_cents", "retained_cents", "pending_cents"}, "refund_to": "pix" | "balance" | null, "balance_cents": int}`.
  - Visão da corrida do passageiro (`passenger_ride_view`) ganha `"cancel": null | {"free_until": float, "fee_cents_now": int}` (só em `accepted`/`arrived`; `free_until = en_route_since + free_cancel_after_accept_s`; `fee_cents_now` vem de `TripService.cancel_fee_preview`).
  - `GET /v1/passenger/state` ganha `"balance_cents"`, `"topup_enabled"`, `"pending_fee"` (`null | {"ride_id", "amount_cents", "charge_id" | null, "appeal": null | {...}}`) e `"recent_fees"` (últimas 5 dentro do prazo do recurso: `{"ride_id", "fee_cents", "created_at", "from_balance_cents", "retained_cents", "pending_cents", "appeal_state", "can_appeal"}`).
  - `POST /v1/passenger/fees/pay` → `200 {"paid": true}` (saldo cobriu) ou `200 {"paid": false, "charge_id", "amount_cents", "br_code"}`; `409 nothing_to_pay`.
  - `POST /v1/passenger/rides/{ride_id}/fee/appeal` corpo `{"text": str}` → `204`; `404 not_found`, `403 not_your_ride`, `409 appeal_not_allowed`, `422 invalid`.
  - `POST /v1/passenger/balance/topup` corpo `{"amount_cents": int}` → `200 {"charge_id", "amount_cents", "br_code"}`; `403 topup_disabled`; `422 invalid`.
  - `GET /v1/admin/appeals?status=open|accepted|rejected&limit&offset` → lista de `AppealItem` (mais antigo primeiro); `POST /v1/admin/appeals/{ride_id}/decide` corpo `{"decision": "accept" | "reject", "note": str ≤ 200}` → `204`; `409 appeal_not_allowed`.
  - `GET /v1/dev/audit` ganha `"balance_matches_ledger": bool` (`passenger_balances_total == ledger_balances_total`) e `"inconsistent_fees": list[str]`; o extrato do provedor falso usa `amount_cents − refunded_cents` e ignora o que está inteiro devolvido.
  - Avisos em tempo real novos (documentar na tabela de `docs/api-v1.md`): `cancel_fee`, `fee_paid`, `balance_changed`, `appeal_opened` (administrador), `appeal_decided`; `payment_refunded` ganha `to`; `ride_cancelled` do motoqueiro ganha `fee_cents`.

- [ ] **Step 1: Testes que falham.** `test_cancel_fee_routes.py` (monta a API como `tests/api/test_passenger_routes.py`: `login`, `online_rider`, relógio manual): `test_visao_da_corrida_mostra_o_fim_da_janela_e_a_taxa_de_agora`; `test_cancelar_tarde_responde_a_taxa_e_o_destino_do_dinheiro` (corpo exato da resposta para um cancelamento em dinheiro sem saldo: `fee_cents`, `fee.pending_cents`, `refund_to null`); `test_estado_mostra_pendencia_e_pedido_novo_e_bloqueado` (`blocked_reason` com a mensagem da taxa; `POST /v1/passenger/rides` → `403 not_allowed`); `test_pagar_a_pendencia_pelo_pix_desbloqueia` (`fees/pay` → `br_code`; `POST /v1/dev/pix/{id}/pay`; estado sem pendência); `test_recurso_pela_api_e_decisao_do_administrador` (aceito: saldo no estado do passageiro sobe; os avisos `appeal_decided` chegam ao `Gravador` do passageiro). `test_balance_routes.py`: recarga desligada → `403 topup_disabled`; ligada por `save_config(..., BalanceConfig(topup_enabled=True))`: gerar a cobrança, pagar pelo `dev`, `balance_cents` no estado; fora dos limites → `422`; `GET /v1/charges/{id}` da recarga só para o dono. `test_admin_appeals.py`: passageiro comum recebe `403`; listar por situação; decidir. `test_dev_audit.py`: `balance_matches_ledger` verdadeiro depois de um cancelamento com saldo e `test_conferencia_acusa_saldo_diferente_do_livro` (muda `passenger_profiles.balance_cents` à mão → falso).
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/api -q` → falha.
- [ ] **Step 3: Implementar** rotas, visões, regras de erro (`NothingToPay`, `TopupDisabled`, `AppealNotAllowed`) e atualizar `docs/api-v1.md` (rotas, campos, erros e tabela de avisos).
- [ ] **Step 4: Rodar e ver passar:** `.venv/bin/python -m pytest tests/api tests/services -q`.
- [ ] **Step 5: Commit**

```bash
git add app docs/api-v1.md tests
git commit -m "feat(api): taxa de cancelamento, saldo, pendência e recurso na API e na conferência do servidor"
```

---

### Task 9: O simulador passa a cancelar, pagar a taxa e recorrer

**Files:**
- Modify: `simulator/behavior.py`, `simulator/passenger.py`, `simulator/admin.py`, `simulator/report.py`, `simulator/sandbox.py`, `simulator/stats.py`, `docs/simulador.md`
- Test: `tests/sim/test_ponta_a_ponta.py`, `tests/sim/test_report.py`, `tests/sim/test_behavior.py`

**Interfaces:**
- Produces: `Profile.pay_fee: float`, `Profile.appeal_fee: float` (`calmo` 1.0 e 0.0; `normal` 0.9 e 0.3; `bagunca` 0.6 e 0.6); no servidor descartável (`seed_database`), a recarga fica **ligada** (`BalanceConfig(topup_enabled=True)`) e `fast=True` põe `free_cancel_after_accept_s = 15` (já existe), então cancelamentos tardios acontecem; o passageiro de mentira, ao cancelar e receber `fee.pending_cents > 0`, paga a pendência (`POST /v1/passenger/fees/pay` e, se vier `br_code`, `pay_pix`) com a probabilidade do perfil, e com `appeal_fee` pede revisão de uma taxa recente (`POST /v1/passenger/rides/{ride_id}/fee/appeal`); o administrador de mentira lista `GET /v1/admin/appeals?status=open` a cada rodada e decide aceitar ou recusar (50/50 com a semente); o relatório mostra "taxas de cancelamento cobradas: N (R$ total), recursos: abertos/aceitos/recusados"; novos problemas do veredito: `balance_matches_ledger` falso, `inconsistent_fees` não vazio, e passageiro que ficou bloqueado por pendência até o fim da rodada sem ter escolhido não pagar.

- [ ] **Step 1: Testes que falham:** `test_rodada_com_cancelamento_tardio_cobra_a_taxa_e_o_livro_fecha` (perfil `bagunca`, `--fast`, semente fixa, 2 motoqueiros e 4 passageiros, 2 minutos: o relatório conta ao menos 1 taxa e o veredito é "Tudo certo."); `test_passageiro_que_nao_paga_a_taxa_aparece_como_bloqueado_no_relatorio`; `test_conferencia_com_saldo_diferente_reprova_a_rodada`; `test_perfis_novos_tem_probabilidades_validas`.
- [ ] **Step 2: Rodar:** `.venv/bin/python -m pytest tests/sim -q -m "not slow"` → falha.
- [ ] **Step 3: Implementar** o que está em Interfaces; atualizar o guia (`docs/simulador.md`: o que o simulador passou a cobrir e como ler as linhas novas do relatório).
- [ ] **Step 4: Rodar e ver passar** o mesmo comando; depois uma rodada de verdade, fora dos testes, com o computador parado: `.venv/bin/python -m simulator demo --fast --riders 6 --passengers 20 --minutes 3 --profile bagunca --seed 7` → termina com "**Tudo certo.**" e mostra taxas cobradas.
- [ ] **Step 5: Commit**

```bash
git add simulator tests/sim docs/simulador.md
git commit -m "feat(sim): passageiro de mentira cancela tarde, paga a taxa e recorre; o administrador decide"
```

---

### Task 10: Fechamento

**Files:**
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`, `server/README.md` (se citar parâmetros), memória do projeto (`project-ride-app-reconcavo.md`, `MEMORY.md`)

- [ ] **Step 1: Suíte inteira e banco de desenvolvimento.** `.venv/bin/python -m pytest -q -p no:cacheprovider` (leva uns 3 minutos; tudo verde) e `.venv/bin/alembic upgrade head` seguido de `.venv/bin/alembic current` (mostra `0005 (head)`).
- [ ] **Step 2: Servidor de verdade.** `PYTHONPATH=. .venv/bin/python scripts/smoke_server.py` termina bem.
- [ ] **Step 3: Roteiro.** Marcar o plano 4B como feito; riscar "falta transformar a decisão em código" do cancelamento tardio; registrar o que sobrou (itens abertos abaixo) e que o saldo do passageiro está construído com a recarga desligada, à espera do advogado; pergunta nova para o advogado: saldo do passageiro com recarga e crédito de devolução (spec 7.5).
- [ ] **Step 4: Memória e commit.**

```bash
git add docs
git commit -m "docs: roteiro com o plano 4B entregue e itens abertos"
```

## Itens que podem sobrar (registrar no roteiro se ocorrerem)

- Conta final do "algoritmo de distância" para o valor da taxa e para o tempo de "sem sinal" (o Levy vai definir).
- Painel (4A): fila de recursos, lista de pendências, saldo de cada passageiro.
- Saldo pagar corrida; saque do saldo; notificação push dos avisos novos.
- Quem arca com a taxa devolvida num recurso aceito: hoje a empresa (decisão 4 deste plano).
