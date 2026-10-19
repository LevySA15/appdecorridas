# Saldo que paga corrida e pode ser sacado — Plano de implementação (plano 4E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cumprir a decisão do Levy de 19/10/2026 sobre o saldo do passageiro: ele **paga corridas** e **pode ser sacado** por Pix (e, no futuro, a empresa poderá dar crédito). O saque nasce **desligado**, esperando o advogado (spec, seção 7.5; pergunta 10).

**Architecture:** Pagar com saldo é uma corrida Pix cuja cobrança é quitada na hora pelo saldo, no aceite da moto: mesma divisão, mesma dívida abatida, mesma devolução e mesma taxa de cancelamento retida, mas o dinheiro sai de `balance:<id>` em vez do provedor e **volta sempre para o saldo**. O saque debita o saldo, lança no livro (`balance:<id>` → `provider`) e manda o Pix pelo provedor; se o provedor falhar, a transação inteira é desfeita.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (PostgreSQL), Redis, pytest. Nenhuma biblioteca nova.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 7.2, 7.5 e 7.6). Decisões do Levy (19/10/2026) no roteiro dos planos, "Decisões já tomadas" (Respostas finais): o saldo "pode ser sacado também"; "no futuro, se for possível, liberar crédito".

## Global Constraints

- **Livro-caixa:** cada `ref` soma zero e a tabela só recebe lançamentos novos. Pagamento com saldo usa a `ref` `charge:<id>` (tipo `ride_payment`); saque usa `withdraw:<id>` (tipo novo `withdrawal`).
- **O dinheiro de um pagamento com saldo nunca vai ao provedor:** a devolução vai sempre para o saldo (`post_refund_to_balance`), com a taxa de cancelamento retida pelo motoqueiro, como no Pix.
- **Saldo cobre a corrida inteira ou não vale:** não se mistura saldo com Pix numa corrida só (decisão deste plano).
- **Ordem de travas:** corrida, motoqueiro, cobrança, passageiro por último, depois a linha da taxa de cancelamento. Nenhum serviço faz `commit`.
- **Saque desligado por padrão** (`BalanceConfig.withdraw_enabled = False`). Pagar corrida com saldo vem **ligado** (`pay_rides_enabled = True`): o saldo só existe por devolução, recurso aceito ou recarga (esta última também desligada).
- **Chave Pix do saque:** o servidor recebe a chave inteira só para mandar ao provedor; no banco fica **apenas o final mascarado** (LGPD).
- Os testes usam o Redis banco 15; o simulador usa 14 (testes do simulador, 13). `systemctl is-active postgresql redis-server` deve responder `active` duas vezes. Todos os comandos partem da pasta `server/`.
- Textos para a pessoa em português do Brasil, simples. Comentários e docstrings em português; nomes de código em inglês.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Um comando de git por vez.

## Review Focus

1. **Devolução de corrida paga com saldo** (cancelar de graça, cancelar tarde, passageiro que não aparece, sair da fila): o valor volta ao saldo, o livro fecha, o provedor nunca é chamado, a dívida do motoqueiro volta/solta como no Pix. Tarefas 1 e 5.
2. **Saldo que mudou entre o pedido e o aceite** (pagou uma taxa, sacou): a corrida segue como Pix comum, sem perder o passageiro nem cobrar duas vezes. Tarefa 4.
3. **Saque que falha no provedor:** nada é debitado nem lançado; saque repetido não passa do saldo; saque com taxa pendente é recusado; limites mínimo e máximo. Tarefa 6.
4. **Chave Pix inválida ou de outro tipo** (CPF com dígitos errados, e-mail sem arroba): recusada antes de qualquer débito. Tarefa 2.
5. **Conta do dono:** o total dos saldos continua igual ao do livro-caixa depois de pagar corrida, devolver e sacar (`balance_matches_ledger`), e o extrato do provedor falso inclui os saques. Tarefas 6 e 8.

## Decisões deste plano (o Levy confere)

1. **Só paga com saldo se ele cobre a corrida inteira.** Sobra de saldo menor que o preço continua servindo à taxa de cancelamento. Misturar saldo com Pix pede duas cobranças por corrida; fica para depois, se fizer falta.
2. **O saldo é cobrado no aceite da moto** (junto com a criação do Pix das corridas Pix), não no pedido: se ele deixar de cobrir até lá, a corrida vira Pix comum e o passageiro é avisado (`balance_short`).
3. **Corrida paga com saldo aparece como `method: "pix"` para o motoqueiro e para o painel,** com `pay_with_balance: true` na visão do passageiro; o motoqueiro não precisa saber a diferença (já está pago).
4. **Saque de R$ 5,00 a R$ 500,00 por vez,** desligado até o advogado; recusado enquanto o passageiro tem taxa pendente; a chave é mascarada no banco.
5. **O provedor falso paga na hora.** Um provedor real avisa depois que o Pix falhou: tratar essa falha é do plano 7 (devolver o valor ao saldo).
6. **Crédito dado pela empresa (promoção) não existe ainda:** o saldo é um número só, sem parte "não sacável". Quando o Levy quiser promoção, é preciso separar o saldo em dois (migração).
7. **Corrida paga com saldo: a parte do motoqueiro entra no livro e ele é avisado, mas o dinheiro só chega a ele no plano 7** (não há divisão pelo provedor; a empresa guarda o valor). Mesma lacuna da taxa de cancelamento paga do saldo. Ver "Itens que sobraram do plano 4E" no roteiro.
8. **Fora deste plano:** tela do painel para saques (o painel ganha só a rota `GET /v1/admin/withdrawals`), validade do saldo, limite diário de saque, saque de motoqueiro.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `app/domain/ledger.py`, `app/db/pg_ledger.py` | pagamento com saldo, devolução só para o saldo, saque |
| `app/domain/config.py`, `app/domain/pix_key.py` | parâmetros do saque; validação e máscara da chave Pix |
| `app/domain/rides.py`, `app/domain/payments.py`, `app/domain/balance.py` | `Ride.pay_with_balance`, `PixCharge.source`, `Withdrawal` |
| `app/db/models.py`, `repositories.py`, `migrations/versions/0010_*.py` | colunas e tabela `withdrawals` |
| `app/adapters/fake_payments.py` | `payout` do provedor falso |
| `app/services/ride_requests.py`, `payments.py`, `dispatch.py` | pedido com saldo, cobrança no aceite, devolução ao saldo |
| `app/services/passenger_money.py`, `app/api/*` | saque, rotas, erros, visões |
| `simulator/*`, `docs/*` | passageiro de mentira que paga com saldo e saca; guias |

---

### Task 1: Livro-caixa — pagar com saldo e sacar

**Files:**
- Modify: `app/domain/ledger.py`, `app/db/pg_ledger.py`
- Test: `tests/domain/test_ledger_saldo_corrida.py` (novo), `tests/db/test_pg_ledger_saldo_corrida.py` (novo)

**Interfaces:**
- Produces: `EntryKind.WITHDRAWAL = "withdrawal"`;
  `Ledger.post_charge_payment_from_balance(charge_id: str, passenger_id: str, rider_id: str, price_cents: int, split: Split) -> None` (ref `charge:<id>`, tipo `RIDE_PAYMENT`: `balance:<p>` −preço, `rider:<r>` +parte do motoqueiro, `company` +parte da empresa);
  `Ledger.post_withdrawal(withdrawal_id: str, passenger_id: str, amount_cents: int) -> None` (ref `withdraw:<id>`: `balance:<p>` −valor, `provider` +valor);
  os mesmos dois em `PgLedger`.
- `Ledger._reverse` passa a achar a conta de origem do pagamento (o lançamento negativo, `provider` ou `balance:<p>`); devolver para o provedor um pagamento feito com saldo levanta `ValueError("pagamento feito com saldo só volta para o saldo")`; `post_refund_to_balance` funciona nos dois casos.

- [ ] **Step 1: Testes que falham** (`test_ledger_saldo_corrida.py`): `test_pagamento_com_saldo_soma_zero_e_move_o_saldo_para_motoqueiro_e_empresa` (preço 700, divisão 600/100 → `balance:p1` −700, `rider:r1` 600, `company` 100, `provider` 0); `test_pagamento_com_saldo_repetido_e_recusado`; `test_devolucao_de_pagamento_com_saldo_volta_inteira_para_o_saldo` (`post_refund_to_balance` → `balance:p1` 0, rider e empresa 0); `test_devolucao_com_taxa_retida_deixa_a_taxa_com_o_motoqueiro` (keep 300: rider 300, saldo −400, empresa 0); `test_pagamento_com_saldo_nao_volta_para_o_provedor` (`post_refund` levanta `ValueError` com "saldo"); `test_pagamento_pix_continua_devolvendo_para_o_provedor_e_para_o_saldo` (regressão dos dois caminhos antigos); `test_saque_tira_do_saldo_e_entra_no_provedor` (`balance:p1` −500, `provider` +500, soma zero); `test_saque_repetido_ou_nao_positivo_e_recusado`; `test_extrato_do_provedor_com_saque_confere` (`reconcile({"withdraw:w1": -500}) == {}`). `test_pg_ledger_saldo_corrida.py`: os mesmos casos centrais no PostgreSQL (`session` fixture), incluindo `is_balanced()` e recusa de repetição pelo índice único.
- [ ] **Step 2:** `.venv/bin/pytest tests/domain/test_ledger_saldo_corrida.py tests/db/test_pg_ledger_saldo_corrida.py -q`. Expected: falham (método não existe).
- [ ] **Step 3: Implementar** em `ledger.py` e `pg_ledger.py` conforme as Interfaces (`PgLedger` segue o desenho dos outros métodos: carrega a `ref`, deixa o domínio validar, grava só o novo).
- [ ] **Step 4:** os mesmos testes e `.venv/bin/pytest tests/domain tests/db -q`. Expected: tudo passa.
- [ ] **Step 5: Commit** `feat(livro): pagamento com saldo, devolução só para o saldo e saque`.

---

### Task 2: Parâmetros do saque, chave Pix, colunas e tabela

**Files:**
- Create: `app/domain/pix_key.py`, `migrations/versions/0010_saldo_paga_corrida_e_saque.py`
- Modify: `app/domain/config.py`, `app/domain/rides.py`, `app/domain/payments.py`, `app/domain/balance.py`, `app/db/models.py`, `app/db/repositories.py`
- Test: `tests/domain/test_pix_key.py` (novo), `tests/db/test_config_store.py`, `tests/db/test_repositories_saldo.py`, `tests/api/test_admin_panel_write.py`

**Interfaces:**
- Produces: `BalanceConfig.pay_rides_enabled: bool = True`, `withdraw_enabled: bool = False`, `withdraw_min_cents: int = 500`, `withdraw_max_cents: int = 50_000` (validação: mínimo > 0 e máximo ≥ mínimo, mensagem com "saque");
  `app/domain/pix_key.py`: `@dataclass(frozen=True) class PixKey: kind: str; value: str; masked: str` e `normalize_pix_key(raw: str) -> PixKey` (levanta `ValueError("Chave Pix inválida.")`). Tipos: `cpf` (11 dígitos com dígitos verificadores certos), `cnpj` (14 dígitos com verificadores certos), `phone` (`+55` + 10 ou 11 dígitos; **sem `+55` é recusado**, para um CPF digitado errado não virar o telefone de outra pessoa), `email` (um `@`, ponto no domínio, até 77 letras), `random` (UUID com 32 hex). `masked` = `"final " + últimos 4 caracteres do valor normalizado` (e-mail: `"final "` + últimos 4);
  `Ride.pay_with_balance: bool = False`; `PixCharge.source: str = "pix"` (`"pix"` ou `"balance"`); `Withdrawal` em `balance.py`: `withdrawal_id, passenger_id, amount_cents, key_kind, key_masked, provider_ref, created_at`;
  repositórios: `add_withdrawal(session, w: Withdrawal)`, `list_withdrawals(session, limit=50, offset=0) -> list[Withdrawal]` (mais novo primeiro), e as colunas novas lidas e gravadas em `Ride` e `PixCharge`.
- Banco: `rides.pay_with_balance boolean not null default false`; `pix_charges.source varchar(8) not null default 'pix'` com CHECK `source IN ('pix','balance')`; tabela `withdrawals` (`id varchar(40)` PK, `passenger_id` FK `users.id`, `amount_cents integer` > 0, `key_kind varchar(10)`, `key_masked varchar(40)`, `provider_ref varchar(60)`, `created_at float`).

- [ ] **Step 1: Testes que falham:** `test_pix_key.py` (CPF válido `529.982.247-25` → `cpf`, `52998224725`, masked `final 4725`; CPF com dígito errado e CPF de dígitos repetidos recusados; CNPJ válido `11.222.333/0001-81`; telefone `(75) 98851-0824` → `+5575988510824`; e-mail válido e `sem-arroba`; UUID aleatório; texto vazio e lixo recusados; espaços nas pontas ignorados). `test_config_store.py`: padrões novos (`pay_rides_enabled` True, `withdraw_enabled` False, 500/50 000), configuração antiga sem os campos carrega, e `{"withdraw_min_cents": 0}`, `{"withdraw_min_cents": 900, "withdraw_max_cents": 800}` não salvam (`ValueError` com "saque"). `test_repositories_saldo.py`: ida e volta de `Ride.pay_with_balance`, `PixCharge.source` e `Withdrawal` (`add_withdrawal`, `list_withdrawals` na ordem certa); o banco recusa `source='x'`. `test_admin_panel_write.py`: `("balance", {"withdraw_min_cents": 900, "withdraw_max_cents": 800}, 422)`.
- [ ] **Step 2:** rodar esses arquivos. Expected: falham.
- [ ] **Step 3: Implementar** (`validate_balance_config` ganha o saque; `normalize_pix_key` em módulo próprio; migração 0010 com `downgrade`; modelos e repositórios).
- [ ] **Step 4:** `.venv/bin/alembic upgrade head`, `.venv/bin/pytest tests/domain tests/db tests/api/test_admin_panel_write.py -q`. Expected: passa; `alembic current` → `0010 (head)`.
- [ ] **Step 5: Commit** `feat(saldo): parâmetros do saque, chave Pix, colunas e tabela de saques`.

---

### Task 3: Provedor — pagar saque

**Files:**
- Modify: `app/domain/payments.py` (Protocol), `app/adapters/fake_payments.py`
- Test: `tests/adapters/test_fake_payments.py` (existente ou novo)

**Interfaces:**
- Produces: `PaymentProvider.payout(withdrawal_id: str, pix_key: str, amount_cents: int) -> str` (devolve a referência do provedor; levanta `PaymentProviderError` se não conseguir); `FakePaymentProvider.payouts: dict[str, tuple[str, int]]` (`withdrawal_id` → `(chave, valor)`), `FakePaymentProvider.fail_payouts: bool = False`; mesmo `withdrawal_id` repetido não paga duas vezes (devolve a mesma referência).

- [ ] **Step 1: Testes que falham:** `test_payout_registra_e_devolve_referencia`, `test_payout_repetido_nao_paga_duas_vezes`, `test_payout_com_provedor_fora_do_ar_levanta_erro_de_pagamento_e_nao_registra`.
- [ ] **Step 2:** rodar. Expected: falham.
- [ ] **Step 3: Implementar** no Protocol e no provedor falso.
- [ ] **Step 4:** rodar. Expected: passam.
- [ ] **Step 5: Commit** `feat(pagamentos): saque pelo provedor (falso)`.

---

### Task 4: Pedir e pagar a corrida com o saldo

**Files:**
- Modify: `app/services/ride_requests.py`, `app/services/payments.py`, `app/services/dispatch.py`, `app/runtime.py`, `app/api/routes/passenger.py`
- Test: `tests/services/test_pay_with_balance.py` (novo), `tests/api/test_balance_routes.py`

**Interfaces:**
- Consumes: Tarefas 1 a 3.
- Produces: `RideRequestService.request_ride(session, passenger_id, quote_id, method, now, pay_with_balance: bool = False) -> Ride`: com `pay_with_balance`, `method` precisa ser `PIX`; recusa (`NotAllowed`) se `BalanceConfig.pay_rides_enabled` é falso ("Pagar com o saldo não está disponível agora.") ou se o saldo não cobre o preço da cotação ("Seu saldo não cobre esta corrida. Escolha outro jeito de pagar."); grava `Ride.pay_with_balance` e o evento `requested` leva `pay_with_balance`;
  `PaymentService(provider, fee_cfg, ride_cfg, events, positions, balance_cfg: BalanceConfig | None = None)`;
  `PaymentService.start_pix_charge` — para corrida com `pay_with_balance`: se o saldo cobre o preço e `pay_rides_enabled`, **cria a cobrança já paga** (`PixCharge(charge_id=new_id("bal"), source="balance", paid=True, br_code="")`, sem chamar o provedor), reserva e confirma a divisão da dívida como no Pix, debita o saldo, lança `post_charge_payment_from_balance`, `on_pix_paid(ride)`, e avisa o passageiro (`balance_paid`: `ride_id, amount_cents, balance_cents`) e o motoqueiro (`payment_received`: `ride_id, late: False`); se o saldo não cobre mais, tira `pay_with_balance` da corrida, avisa o passageiro (`balance_short`: `ride_id, balance_cents, price_cents`) e segue com o Pix comum;
  `PaymentService._refund` — para cobrança com `source == "balance"` não chama o provedor: lança `post_refund_to_balance` e credita `send` ao saldo (destino `"balance"`);
  `DispatchService.accept_offer` — o evento `rider_accepted` ao passageiro leva `pay: None` quando a cobrança já está paga e `paid_with_balance: true`;
  rota `POST /v1/passenger/rides` aceita `method: "pix" | "cash" | "balance"` (`balance` vira `PIX` + `pay_with_balance`; a checagem de Pix fora do ar só vale para `pix`).

- [ ] **Step 1: Testes que falham** (`test_pay_with_balance.py`): `test_pedido_com_saldo_que_cobre_grava_a_marca`; `test_pedido_com_saldo_curto_e_recusado`; `test_pedido_com_saldo_desligado_e_recusado`; `test_pedido_com_saldo_so_vale_para_pix` (`method` dinheiro → erro); `test_aceite_paga_com_o_saldo_e_o_livro_fecha` (saldo 1000, preço 700, taxa 100: saldo 300, `rider:r1` 600, `company` 100, `provider` 0, `pix_paid` verdadeiro, cobrança `source == "balance"`, `provider.charges` vazio, eventos `balance_paid` e `payment_received`, `rider_accepted.pay is None`); `test_aceite_com_divida_do_motoqueiro_abate_como_no_pix` (dívida 60: empresa fica com taxa + abatimento, `confirm_charge_debt` aplicado); `test_saldo_que_ficou_curto_antes_do_aceite_vira_pix_comum` (gasta o saldo entre o pedido e o aceite; a corrida tem cobrança Pix do provedor, `pay_with_balance` falso, evento `balance_short`, janela do Pix valendo); `test_corrida_paga_com_saldo_comeca_sem_esperar_pix` (`start_ride` não levanta); `test_saldo_exato_do_preco_zera_o_saldo`; rota: `test_rota_aceita_method_balance_e_recusa_sem_saldo` em `tests/api/test_balance_routes.py` (`201` com `pay_with_balance` na resposta é conferido na Tarefa 7; aqui basta o status e o erro `not_allowed`).
- [ ] **Step 2:** `.venv/bin/pytest tests/services/test_pay_with_balance.py tests/api/test_balance_routes.py -q`. Expected: falham.
- [ ] **Step 3: Implementar** conforme as Interfaces (`Runtime.make_unit` passa `cfg.balance` ao `PaymentService`).
- [ ] **Step 4:** os mesmos testes e `.venv/bin/pytest -q -m "not slow"`. Expected: tudo passa.
- [ ] **Step 5: Commit** `feat(saldo): pagar a corrida com o saldo`.

---

### Task 5: Cancelar, sair da fila e esperar — corrida paga com saldo

**Files:**
- Modify: `app/services/payments.py` (só se algum caso exigir)
- Test: `tests/services/test_pay_with_balance_cancel.py` (novo)

**Interfaces:**
- Consumes: Tarefa 4.
- Produces: nenhum código novo esperado: esta tarefa prova que cancelamento, taxa retida, fila e tempo de espera funcionam com `source == "balance"`; qualquer correção que os testes exijam entra aqui com a mesma disciplina RED→GREEN.

- [ ] **Step 1: Testes** (usam o ambiente de `tests/services/test_cancel_fee.py`: moto, `aceitar`, saldo com `saldo(session, cents)`; o saldo precisa vir de crédito real no livro, como em `tests/services/helpers_money.py::recarregar`): `test_cancelar_dentro_da_janela_devolve_tudo_ao_saldo_sem_chamar_o_provedor` (`refund_to == "balance"`, saldo volta ao de antes, `provider.charges == {}`, livro fecha, `rider:r1` e empresa em zero); `test_cancelar_tarde_retem_a_taxa_e_devolve_o_resto_ao_saldo` (moto com 900 m andados, taxa R$ 4,00: `retained_cents == 400`, saldo = antes − 400); `test_taxa_sai_do_outro_saldo_quando_ele_cobre` (sobra de saldo cobre a taxa: `from_balance_cents` > 0, devolução inteira ao saldo); `test_passageiro_que_nao_aparece_paga_cinco_reais_e_o_resto_volta_ao_saldo` (`cancel_after_arrival_timeout`); `test_sair_da_fila_devolve_ao_saldo_e_o_novo_aceite_cobra_de_novo` (corrida na fila de moto ocupada: `release_queued_ride` devolve; novo aceite por outra moto paga de novo com o saldo); `test_dividas_do_motoqueiro_voltam_na_devolucao` (dívida abatida no aceite volta a subir no cancelamento); `test_recurso_aceito_de_corrida_paga_com_saldo_devolve_o_que_foi_cobrado` (taxa retida do pagamento com saldo: `credited_back_cents` certo, livro fecha, soma dos saldos = livro).
- [ ] **Step 2:** `.venv/bin/pytest tests/services/test_pay_with_balance_cancel.py -q`. Expected: os que dependem de comportamento ainda não coberto falham; os que já funcionam (por reaproveitar o caminho do Pix) passam, e isso fica registrado no livro de tarefas.
- [ ] **Step 3: Corrigir** o que falhar, no `payments.py`.
- [ ] **Step 4:** `.venv/bin/pytest tests/services -q`. Expected: tudo passa.
- [ ] **Step 5: Commit** `test(saldo): cancelamento, fila e espera de corrida paga com saldo`.

---

### Task 6: Sacar o saldo

**Files:**
- Modify: `app/services/passenger_money.py`, `app/api/routes/passenger.py`, `app/api/routes/admin.py`, `app/api/errors.py`, `app/api/routes/dev.py`, `app/runtime.py`
- Test: `tests/services/test_withdraw.py` (novo), `tests/api/test_balance_routes.py`, `tests/api/test_dev_audit.py`

**Interfaces:**
- Consumes: Tarefas 1 a 3.
- Produces: `PassengerMoneyService.withdraw(session, passenger_id: str, amount_cents: int, pix_key: str, now: float) -> Withdrawal`. Ordem: confere que o saque está ligado (`WithdrawDisabled(NotAllowed)`, código `withdraw_disabled`, 403), valida o valor (`ValueError` "O saque vai de R$ 5,00 a R$ 500,00."), normaliza a chave (`ValueError` "Chave Pix inválida."), trava o passageiro, recusa com taxa pendente (`NotAllowed` "Pague a taxa pendente antes de sacar.") e saldo menor que o valor (`NotAllowed` "Seu saldo é menor que o valor do saque."), debita (`spend_up_to`), lança `post_withdrawal`, chama `provider.payout`, grava `Withdrawal` (só a chave mascarada) e avisa o passageiro (`balance_changed`: `balance_cents`; `withdrawal_done`: `withdrawal_id, amount_cents, balance_cents`). Se `payout` levantar `PaymentProviderError`, nada fica gravado (a transação é desfeita por quem chama);
  `POST /v1/passenger/balance/withdraw` com `{"amount_cents": int, "pix_key": str}` → `201 {"withdrawal_id","amount_cents","balance_cents","key"}` (`key` é a máscara); `GET /v1/admin/withdrawals?limit&offset` (só administrador): `[{"withdrawal_id","passenger_id","passenger_name","amount_cents","key_kind","key_masked","created_at"}]`; registro da ação não é necessário (é leitura);
  `GET /v1/dev/audit`: o extrato do provedor falso inclui os saques (`withdraw:<id>` → `−valor`), então `reconcile_diff` continua vazio.

- [ ] **Step 1: Testes que falham** (`test_withdraw.py`): `test_saque_desligado_e_recusado`; `test_saque_debita_lanca_no_livro_e_manda_o_pix` (saldo 2000, saca 1500 para CPF válido: saldo 500, `balance:p1` 500, `provider` +1500, `provider.payouts` com a chave inteira, `Withdrawal.key_masked == "final 4725"`, evento); `test_saque_maior_que_o_saldo_e_recusado_e_nao_muda_nada`; `test_saque_abaixo_do_minimo_e_acima_do_maximo`; `test_chave_invalida_e_recusada_antes_de_debitar`; `test_saque_com_taxa_pendente_e_recusado`; `test_provedor_fora_do_ar_nao_deixa_rastro` (`fail_payouts = True`, usa `Runtime.run` ou `session.rollback()` como nos testes de dinheiro para provar que saldo, livro e tabela voltam ao que eram); `test_dois_saques_seguidos_nao_passam_do_saldo`; `test_chave_inteira_nao_fica_no_banco` (varre `withdrawals.key_masked` e confere que o CPF inteiro não aparece). API (`test_balance_routes.py`): `test_rota_de_saque_desligada_responde_withdraw_disabled`, `test_rota_de_saque_ligada_responde_201_e_a_mascara`, `test_rota_de_saque_com_chave_ruim_responde_422`, `test_lista_de_saques_so_para_administrador`. `test_dev_audit.py`: `test_saque_aparece_no_extrato_e_a_diferenca_continua_vazia`.
- [ ] **Step 2:** rodar esses arquivos. Expected: falham.
- [ ] **Step 3: Implementar** conforme as Interfaces (`WithdrawDisabled` com o mesmo desenho de `TopupDisabled`, mapeado em `errors.py`).
- [ ] **Step 4:** rodar esses arquivos e `.venv/bin/pytest -q -m "not slow"`. Expected: passa.
- [ ] **Step 5: Commit** `feat(saldo): sacar o saldo por Pix`.

---

### Task 7: Visões, estado do passageiro e contrato

**Files:**
- Modify: `app/api/views.py`, `app/api/routes/passenger.py`, `app/db/queries.py`, `docs/api-v1.md`
- Test: `tests/api/test_balance_routes.py`, `tests/api/test_passenger_routes.py`, `tests/api/test_admin_panel_read.py`

**Interfaces:**
- Consumes: Tarefas 4 e 6.
- Produces: `quote_view` e a resposta de `POST /v1/passenger/quotes` listam `"balance"` em `payment_methods` **só** quando `pay_rides_enabled` e o saldo cobre o preço da cotação; `passenger_state` ganha `pay_with_balance_enabled`, `withdraw_enabled`, `withdraw_min_cents`, `withdraw_max_cents`; `passenger_ride_view` ganha `pay_with_balance` (booleano); `queries.money_summary` ganha `passenger_balances_cents` (soma dos saldos) e `withdrawn_cents` (soma dos saques); `docs/api-v1.md` descreve `method: "balance"`, as visões novas, os dois eventos de saldo da Tarefa 4 e os da Tarefa 6, `POST /v1/passenger/balance/withdraw` e `GET /v1/admin/withdrawals`.

- [ ] **Step 1: Testes que falham:** `test_cotacao_oferece_saldo_so_quando_cobre`; `test_estado_do_passageiro_traz_as_chaves_do_saldo`; `test_visao_da_corrida_paga_com_saldo_marca_pay_with_balance_e_nao_mostra_pix`; `test_resumo_de_dinheiro_soma_saldos_e_saques`.
- [ ] **Step 2:** rodar. Expected: falham.
- [ ] **Step 3: Implementar** e atualizar o contrato.
- [ ] **Step 4:** rodar e `.venv/bin/pytest -q -m "not slow"`. Expected: passa.
- [ ] **Step 5: Commit** `feat(saldo): visões, estado e contrato do saldo que paga e saca`.

---

### Task 8: Simulador — passageiro que paga com saldo e saca

**Files:**
- Modify: `simulator/behavior.py`, `simulator/passenger.py`, `simulator/report.py`, `simulator/sandbox.py`, `docs/simulador.md`
- Test: `tests/sim/test_behavior.py`, `tests/sim/test_report.py`, `tests/sim/test_ponta_a_ponta.py`

**Interfaces:**
- Consumes: Tarefas 4, 6 e 7.
- Produces: no `Profile`: `use_balance: float` (chance de pagar com o saldo quando ele cobre a corrida) e `withdraw: float` (chance de sacar o saldo ao ficar livre, com saldo acima do mínimo), zero em `calmo`, `normal` e `bagunca` salvo o que a rodada ligar; o relatório ganha na seção do saldo "Corridas pagas com saldo: N, saques: N, R$ X"; `sandbox.py` liga `withdraw_enabled` no servidor descartável; o relatório falha se `balance_matches_ledger` for falso ou `reconcile_diff` não for vazio (conferências que já existem).

- [ ] **Step 1: Testes que falham:** `test_behavior`: as novas chances validam o intervalo 0 a 1 e `preset("calmo")` as deixa em zero; `test_report`: o texto traz as duas linhas novas e reprova com diferença no extrato; `test_ponta_a_ponta` (lento): `test_rodada_em_que_o_passageiro_paga_a_segunda_corrida_com_o_saldo_e_saca_o_que_sobrou` — passageiro com `topup=1.0`, `use_balance=1.0`, `withdraw=1.0`, duas corridas, relatório aprovado, `balance_matches_ledger` verdadeiro.
- [ ] **Step 2:** rodar. Expected: falham.
- [ ] **Step 3: Implementar** (o passageiro de mentira só escolhe `balance` se `payment_methods` da cotação o oferece; o saque usa um CPF válido fixo do simulador).
- [ ] **Step 4:** `.venv/bin/pytest tests/sim -q`. Expected: passa.
- [ ] **Step 5: Commit** `feat(simulador): passageiro que paga com o saldo e saca`.

---

### Task 9: Fechamento — documentos, suíte inteira e memória do roteiro

**Files:**
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`, `docs/pesquisa-taxas-e-precos.md` (nada), `server/README.md` (só se a lista de rotas citar o saldo)
- Test: suíte inteira

**Interfaces:**
- Consumes: todas as anteriores.
- Produces: roteiro atualizado (tabela de planos com o 4E, "Itens que sobraram do plano 4E", pergunta 10 do advogado já escrita), sem código novo.

- [ ] **Step 1:** `.venv/bin/pytest -q` (inclui as rodadas lentas). Expected: tudo passa; anotar o total.
- [ ] **Step 2:** escrever no roteiro a seção "Itens que sobraram do plano 4E" com as decisões deste plano que o Levy confere e os menores adiados.
- [ ] **Step 3: Commit** `docs: roteiro com o plano 4E`.
