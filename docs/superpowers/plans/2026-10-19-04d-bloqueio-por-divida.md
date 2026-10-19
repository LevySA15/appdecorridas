# Bloqueio por dívida do motoqueiro — Plano de implementação (plano 4D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cumprir a regra do Levy para quem deve a taxa das corridas em dinheiro: o motoqueiro tem **uma corrida de folga** e depois fica **bloqueado de aceitar qualquer corrida** (nenhuma oferta aparece, e o botão "estou rodando / não estou rodando" fica preso em "não estou") até pagar a dívida. Para pagar, ele ganha uma cobrança Pix própria da dívida.

**Architecture:** O bloqueio entra no mesmo caminho da "entrada pendente" (`offer_block_reason` em `app/domain/fees.py`), que já recusa ofertas, recusa `go_online` e desfaz a fila. A dívida passa a bloquear quando chega ao limite, que deixa de ser R$ 10 e vira "uma taxa" (qualquer taxa cobrada em dinheiro vivo já alcança o limite). Quando a dívida cruza o limite com o motoqueiro disponível, ele é posto em "não estou" na hora e avisado. O pagamento é uma cobrança Pix nova (`purpose = "debt"`), tratada pelo aviso do provedor como a entrada de R$ 50.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (PostgreSQL), Redis, pytest. Nenhuma biblioteca nova.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seção 7.2, "taxa das corridas em dinheiro vivo" e seção 7.6). Decisão do Levy (18 e 19/10/2026) no roteiro dos planos, "Decisões já tomadas" (calote): sem saldo, o motoqueiro "não pode aceitar corrida até pagar, mas ainda faz uma corrida antes do bloqueio"; em 19/10: "ele tem uma corrida de folga, depois dessa ele é bloqueado de aceitar qualquer corrida, nem aparece para ele, aquele coiso de 'Estou rodando' e 'Não estou rodando' fica preso em 'não estou'". Este é o plano 4D, depois do 4C.

## Global Constraints

- **Limite de dívida = uma taxa.** `FeeConfig.cash_debt_limit_cents` passa de 1000 para **70** (o piso de lucro, `min_fee_cents`): toda taxa cobrada em dinheiro vivo (de R$ 0,80 a R$ 1,00 nas faixas de hoje) já alcança o limite, e por isso a corrida que gera a primeira dívida é a "corrida de folga". Bloqueia quando `cash_debt_cents >= cash_debt_limit_cents`.
- O bloqueio vale para **todas** as ofertas (dinheiro e Pix); não bloqueia corrida já aceita nem em andamento (nunca derrubar corrida): a fila é devolvida à busca quando a corrida atual acaba, como já acontece com a entrada pendente.
- Quem está bloqueado só sai pagando a dívida por Pix (`POST /v1/rider/debt-charge`). A cobrança é do valor `cash_debt_cents − debt_reserved_cents` (a parte reservada por Pix de corrida pendente não entra).
- A dívida paga pelo Pix vira receita da empresa no livro-caixa (provedor −valor, empresa +valor) e diminui `cash_debt_cents`; repetir o aviso do provedor não paga duas vezes.
- Depois de pagar, o motoqueiro **não** volta sozinho a "estou rodando": ele toca no botão (que passa a funcionar).
- Ordem de travas: corrida, motoqueiro, cobrança, passageiro, taxa de cancelamento (como no plano 4B). Nenhum serviço faz `commit`.
- Os testes usam o Redis banco 15; o simulador usa 14 (testes do simulador, 13). `systemctl is-active postgresql redis-server` deve responder `active` duas vezes. Todos os comandos partem da pasta `server/`.
- Textos para a pessoa em português do Brasil, simples. Comentários e docstrings em português; nomes de código em inglês.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Um comando de git por vez.

## Review Focus

1. **Dívida que cruza o limite com o motoqueiro no meio de algo:** disponível sem corrida (vira "não estou" na hora), com corrida em andamento (a corrida segue; ao acabar ele fica "não estou"), com corrida na fila (volta para a busca, com devolução do Pix se já pago), com oferta pendente (a oferta some e aceitar dá erro). Tarefa 2.
2. **Pagar a dívida:** valor certo mesmo com parte reservada; aviso repetido não paga duas vezes; pagar quando a dívida já mudou no meio tempo (devolve o excesso); não existe cobrança aberta duplicada. Tarefa 3.
3. **Quem não deve nada nunca é bloqueado,** e quem deve menos que o limite (por exemplo depois de abater parte com um Pix) volta a poder rodar. Tarefa 1.
4. **A conta do motoqueiro sempre explica o bloqueio** (`blocked_reason`), com o valor devido, para o app mostrar. Tarefa 4.
5. **Corrida em dinheiro cuja confirmação vem tarde** (o motoqueiro confirma o dinheiro depois de já ter outra corrida) também aplica o bloqueio. Tarefa 2.

## Decisões deste plano (o Levy confere)

1. **Limite de uma taxa = R$ 0,70** (o piso de lucro), em vez de "exatamente a taxa da corrida", porque a taxa muda de R$ 1,00 para R$ 0,80 conforme a faixa do dia. Efeito: a primeira taxa cobrada em dinheiro vivo já bloqueia depois daquela corrida. Se o Levy preferir mais de uma corrida de folga, é só subir o número (parâmetro do banco).
2. **O saldo pré-pago do motoqueiro não existe:** continua sendo dívida (o "saldo do app" do Levy, do ponto de vista do código, é a dívida abatida dos repasses Pix). Saldo pré-pago do motoqueiro entra na dúvida do advogado (spec, seção 7.5).
3. **O motoqueiro bloqueado pode pagar a dívida sozinho, a qualquer hora,** pela cobrança Pix; não depende do administrador. O administrador também pode ajustar a dívida pelo livro (fora deste plano).
4. **Fora deste plano:** mostrar devedores no painel (plano 4A), cobrar dívida de motoqueiro que sumiu, notificação push do bloqueio.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `app/domain/config.py`, `app/domain/fees.py` | limite de uma taxa; o bloqueio por dívida no `offer_block_reason` |
| `app/domain/ledger.py`, `app/db/pg_ledger.py` | lançamento do pagamento da dívida |
| `migrations/versions/0007_pagamento_de_divida.py` | `debt` entre os propósitos de cobrança |
| `app/services/payments.py` | aplicar o bloqueio quando a dívida sobe; cobrança e aviso do pagamento da dívida |
| `app/services/riders.py`, `trips.py`, `dispatch.py` | motivos do bloqueio nas respostas e na fila |
| `app/api/*` | rota da cobrança, estado do motoqueiro, erros, contrato |
| `simulator/*`, `docs/*` | motoqueiro de mentira que paga a dívida; guia |

---

### Task 1: A regra do bloqueio por dívida

**Files:**
- Modify: `app/domain/config.py`, `app/domain/fees.py`
- Test: `tests/domain/test_fees.py`, `tests/domain/test_corrida_dinheiro.py`, `tests/db/test_config_store.py`

**Interfaces:**
- Produces:
  - `FeeConfig.cash_debt_limit_cents` padrão **70**.
  - `offer_block_reason(acc, cfg) -> str | None`: devolve `"entrada_pendente"` como hoje; senão `"divida_pendente"` se `acc.cash_debt_cents >= cfg.cash_debt_limit_cents`; senão `None`. (Entrada primeiro: quem deve as duas coisas vê a entrada.)
  - `can_receive_cash_offers(acc, cfg)` passa a ser só `can_receive_offers(acc, cfg)` (o bloqueio por dívida vale para todas as ofertas).
  - `debt_to_pay_cents(acc: RiderAccount) -> int`: `max(0, cash_debt_cents − debt_reserved_cents)`.

- [ ] **Step 1: Testes que falham.** Em `tests/domain/test_fees.py`: `test_sem_divida_ninguem_e_bloqueado`; `test_primeira_taxa_em_dinheiro_ja_alcanca_o_limite` (dívida de 80 e de 100 bloqueiam; 69 não); `test_entrada_pendente_aparece_antes_da_divida` (as duas pendentes devolvem `"entrada_pendente"`); `test_divida_que_cai_abaixo_do_limite_desbloqueia`; `test_divida_a_pagar_nao_conta_a_parte_reservada` (dívida 100, reservada 40 → 60; dívida 30, reservada 40 → 0 por ser máximo com zero). Em `tests/domain/test_corrida_dinheiro.py`: ajustar os testes antigos que contavam com o limite de R$ 10 (a dívida bloqueia todas as ofertas, não só as em dinheiro). Em `tests/db/test_config_store.py`: o padrão de `FeeConfig().cash_debt_limit_cents` é 70.
- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/domain tests/db/test_config_store.py -q -p no:cacheprovider`.
- [ ] **Step 3: Implementar** o que está em Interfaces.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests -q -p no:cacheprovider --ignore=tests/sim` (arrumar o que dependia do limite antigo, sem enfraquecer as conferências).
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(rules): a dívida de uma taxa bloqueia todas as ofertas do motoqueiro"
```

---

### Task 2: O bloqueio na hora em que a dívida sobe

**Files:**
- Modify: `app/services/payments.py`, `app/services/trips.py`, `app/services/riders.py`, `app/services/dispatch.py`
- Test: `tests/services/test_debt_block.py` (novo), `tests/services/test_trips.py`, `tests/services/test_riders.py`, `tests/services/test_dispatch.py`

**Interfaces:**
- Consumes: `offer_block_reason`, `debt_to_pay_cents`.
- Produces:
  - `PaymentService._enforce_block(session, acc: RiderAccount) -> None` (privado): se `offer_block_reason(acc, fee_cfg) == "divida_pendente"`, põe o motoqueiro em "não estou" (`RiderProfileRow.online = False`) e tira a posição do mapa (`positions.remove`) **se ele não está com corrida em andamento ou a caminho** (nessa hora o `complete_trip` e `after_ride_ends` já cuidam); avisa `debt_required` `{cash_debt_cents, debt_limit_cents}` ao motoqueiro. Chamado por `confirm_cash_received` (depois de `add_cash_fee_debt`) e pelo estorno que devolve dívida abatida (`restore_charge_debt`). `PaymentService` passa a receber `positions` opcional para tirar a moto do mapa.
  - `TripService.complete_trip`: o aviso de bloqueio ao terminar a corrida passa a escolher o evento pelo motivo (`entry_required` para entrada, `debt_required` para dívida) e a por o motoqueiro em "não estou" nos dois casos (já faz para a entrada).
  - `TripService.after_ride_ends`: o registro do histórico e o aviso `queue_released` dizem o motivo certo (`entrada pendente` ou `dívida pendente`).
  - `RiderService.go_online`: levanta `CannotGoOnline("debt_pending", "Você tem uma taxa de R$ X para pagar. Pague para voltar a receber corridas.")` (com `brl(debt_to_pay_cents)`); a entrada continua `entry_pending`.
  - `DispatchService.accept_offer`: recusa (`OfferGone`) quem ficou bloqueado depois da oferta, mesmo que `available` ainda seja verdadeiro.

- [ ] **Step 1: Testes que falham** (`test_debt_block.py`, com os ajudantes de `tests/services/test_trips.py`):
  - `test_confirmar_dinheiro_que_cruza_o_limite_poe_o_motoqueiro_em_nao_estou_e_avisa`.
  - `test_motoqueiro_que_acabou_de_ficar_bloqueado_nao_recebe_oferta_nem_aceita_a_que_tinha`.
  - `test_corrida_em_andamento_segue_e_ao_acabar_o_motoqueiro_fica_em_nao_estou` (a confirmação do dinheiro vem durante a corrida seguinte).
  - `test_corrida_da_fila_volta_para_a_busca_com_devolucao_do_pix_quando_ha_divida` (usa `_com_corrida_na_fila`).
  - `test_go_online_com_divida_diz_quanto_deve_e_o_codigo_debt_pending` e `test_go_online_com_entrada_pendente_continua_entry_pending`.
  - `test_primeira_corrida_em_dinheiro_e_a_de_folga` (fluxo completo: 1ª corrida em dinheiro com o dinheiro confirmado → bloqueado; antes dela podia aceitar).
  - `test_pix_que_abate_a_divida_e_estornado_e_devolve_o_bloqueio`.
- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/services/test_debt_block.py -q -p no:cacheprovider`.
- [ ] **Step 3: Implementar** o que está em Interfaces (ligar `positions` ao `PaymentService` em `Runtime.make_unit`).
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services tests/api -q -p no:cacheprovider`.
- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat(riders): o motoqueiro com dívida fica em \"não estou\" e não recebe nem aceita corrida"
```

---

### Task 3: Pagar a dívida por Pix

**Files:**
- Create: `migrations/versions/0007_pagamento_de_divida.py`
- Modify: `app/domain/ledger.py`, `app/db/pg_ledger.py`, `app/db/models.py`, `app/db/repositories.py`, `app/services/payments.py`
- Test: `tests/domain/test_ledger.py`, `tests/db/test_pg_ledger.py`, `tests/db/test_schema_saldo.py` (ou o arquivo do esquema das cobranças), `tests/services/test_debt_payment.py` (novo), `tests/db/test_migracoes_reversiveis.py`

**Interfaces:**
- Produces:
  - Migração `0007` (`down_revision = "0006"`): `charge_purpose_valid` aceita `'debt'`; `charge_ride_required`: `purpose IN ('entry','topup','debt') OR ride_id IS NOT NULL`; `downgrade` apaga as cobranças `debt` e volta as restrições.
  - `EntryKind.DEBT_PAYMENT = "debt_payment"`; `Ledger.post_debt_payment(charge_id: str, rider_id: str, amount_cents: int)` (provedor −valor, empresa +valor; uma vez por cobrança) e o espelho em `PgLedger`. A devolução do excesso usa o `post_refund` que já existe? **Não:** o excesso é devolvido por `Ledger.post_debt_refund(charge_id, amount_cents)` (provedor +valor, empresa −valor, `EntryKind.REFUND`, uma vez por cobrança).
  - `PaymentService.start_debt_charge(session, rider_id: str) -> PixCharge`: trava o motoqueiro; se `debt_to_pay_cents(acc) == 0` levanta `InvalidTransition("Você não tem taxa para pagar.")`; devolve a cobrança `debt` aberta de mesmo valor ou cria uma (`Split(0, valor, 0)`, `ride_id=""`, `rider_id`, `purpose="debt"`).
  - `on_provider_event` com `purpose == "debt"` → `_on_debt_paid`: trava motoqueiro e cobrança; repetida → `"duplicate"`; `aplicado = min(valor, debt_to_pay_cents(acc))`; lança o pagamento (`post_debt_payment` do valor todo), abate `cash_debt_cents` em `aplicado`; se `aplicado < valor`, devolve o excesso pelo provedor (`provider.refund(charge_id, valor − aplicado)`) e lança `post_debt_refund`; aviso ao motoqueiro `debt_paid` `{cash_debt_cents, amount_cents}`; devolve `"applied"`.

- [ ] **Step 1: Testes que falham** (`test_debt_payment.py`): `test_cobranca_da_divida_tem_o_valor_a_pagar_sem_a_parte_reservada`; `test_sem_divida_nao_gera_cobranca`; `test_pedir_de_novo_devolve_a_mesma_cobranca`; `test_pix_da_divida_abate_a_divida_lanca_no_livro_e_avisa` (livro fecha; dívida zero; motoqueiro pode ficar disponível de novo: `go_online` funciona); `test_aviso_repetido_nao_abate_duas_vezes`; `test_pagar_depois_de_a_divida_ter_diminuido_devolve_o_excesso` (dívida cai de 100 para 60 entre a cobrança e o pagamento: abate 60, devolve 40, livro fecha, `refunded_cents == 40` no provedor falso); `test_pagar_a_divida_nao_mexe_na_entrada_nem_nas_corridas`. Em `tests/domain/test_ledger.py` e `tests/db/test_pg_ledger.py`: os dois lançamentos novos fecham em zero, recusam valor ≤ 0 e repetição. Esquema: cobrança `debt` sem corrida é aceita, sem `rider_id` não.
- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/domain/test_ledger.py tests/db tests/services/test_debt_payment.py -q -p no:cacheprovider`.
- [ ] **Step 3: Implementar** o que está em Interfaces.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests -q -p no:cacheprovider --ignore=tests/sim`.
- [ ] **Step 5: Commit**

```bash
git add migrations app tests
git commit -m "feat(payments): cobrança Pix para o motoqueiro pagar a dívida"
```

---

### Task 4: API, estado do motoqueiro e contrato

**Files:**
- Modify: `app/api/routes/rider.py`, `app/api/views.py`, `app/api/errors.py` (se preciso), `app/api/routes/payments.py` (visibilidade da cobrança `debt`), `app/api/routes/dev.py` (`audit`: a dívida paga entra no extrato), `docs/api-v1.md`
- Test: `tests/api/test_rider_routes.py`, `tests/api/test_payments_routes.py`, `tests/api/test_dev_audit.py`

**Interfaces:**
- Produces:
  - `POST /v1/rider/debt-charge` → 201 `{"charge_id","amount_cents","br_code"}`; 409 `invalid_state` ("Você não tem taxa para pagar.") sem dívida.
  - `GET /v1/rider/state`: `account` ganha `"debt_to_pay_cents"` e `"blocked_reason"` (`"entry_pending"`, `"debt_pending"` ou `null`); `cash_debt_cents` e `cash_debt_limit_cents` continuam.
  - `POST /v1/rider/online` com dívida → 409 com `code: "debt_pending"`.
  - `GET /v1/charges/{id}`: a cobrança `debt` só o motoqueiro dono e o administrador veem; `purpose: "debt"`.
  - Avisos novos: `debt_required` (`cash_debt_cents, debt_limit_cents`) e `debt_paid` (`cash_debt_cents, amount_cents`) ao motoqueiro. `GET /v1/dev/audit` conta a cobrança `debt` paga no extrato do provedor falso pelo ref `charge:<id>`.

- [ ] **Step 1: Testes que falham.** `test_estado_do_motoqueiro_explica_o_bloqueio_por_divida` (depois da primeira corrida em dinheiro confirmada: `blocked_reason == "debt_pending"`, `debt_to_pay_cents` igual à taxa, `registration.online == False`); `test_ficar_disponivel_com_divida_responde_debt_pending`; `test_pagar_a_divida_pela_api_destrava_e_o_motoqueiro_volta_a_ficar_disponivel` (cobrança → `POST /v1/dev/pix/{id}/pay` → estado sem bloqueio → `POST /v1/rider/online` 204 → o gravador do motoqueiro recebeu `debt_paid`); `test_passageiro_nao_ve_a_cobranca_da_divida`; `test_conferencia_do_servidor_fecha_com_a_divida_paga`.
- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/api -q -p no:cacheprovider`.
- [ ] **Step 3: Implementar** as rotas, as visões e atualizar `docs/api-v1.md` (rota nova, campos do estado, código `debt_pending`, avisos novos, propósito `debt`).
- [ ] **Step 4: Rodar e ver passar** o mesmo comando mais `tests/services -q -p no:cacheprovider`.
- [ ] **Step 5: Commit**

```bash
git add app docs tests
git commit -m "feat(api): estado do bloqueio por dívida e rota para pagar a dívida"
```

---

### Task 5: O motoqueiro de mentira deve, é bloqueado e paga

**Files:**
- Modify: `simulator/behavior.py`, `simulator/rider.py`, `simulator/report.py`, `docs/simulador.md`
- Test: `tests/sim/test_behavior.py`, `tests/sim/test_ponta_a_ponta.py`, `tests/sim/test_report.py`

**Interfaces:**
- Produces: `Profile.pay_debt: float` (chance de o motoqueiro bloqueado pagar a dívida: `calmo` 1.0, `normal` 0.9, `bagunca` 0.6); o `RiderActor`, ao ver `account.blocked_reason == "debt_pending"` em `GET /v1/rider/state`, para de tentar ficar disponível, e (com a chance do perfil, depois de uma espera) pede `POST /v1/rider/debt-charge`, paga pelo `dev` e volta a ficar disponível; quem escolhe não pagar fica fora até o fim. O relatório ganha "Dívidas de taxa em dinheiro: bloqueados N, pagaram N" em "O que as pessoas fizeram" (como contagens) e o veredito reprova motoqueiro que ia pagar e terminou a rodada bloqueado.

- [ ] **Step 1: Testes que falham.** Perfis válidos (`pay_debt` entre 0 e 1); `test_motoqueiro_que_deve_a_taxa_e_bloqueado_paga_e_volta_a_trabalhar` (perfil rápido, 1 motoqueiro, 2 passageiros em dinheiro, `pay_debt=1.0`: depois da 1ª corrida o relatório mostra o bloqueio e o pagamento, e a 2ª corrida só acontece depois dele; a rodada passa); `test_motoqueiro_que_escolhe_nao_pagar_fica_bloqueado_e_a_rodada_termina` (`pay_debt=0.0`: só 1 corrida concluída, 1 passageiro sem moto, a rodada passa).
- [ ] **Step 2: Rodar e ver falhar:** `.venv/bin/python -m pytest tests/sim -q -p no:cacheprovider -k "divida or perfis"`.
- [ ] **Step 3: Implementar** o comportamento e atualizar o guia.
- [ ] **Step 4: Rodar e ver passar** o mesmo comando; depois uma rodada de verdade: `.venv/bin/python -m simulator demo --fast --riders 6 --passengers 20 --minutes 3 --profile bagunca --seed 7` termina com "**Tudo certo.**".
- [ ] **Step 5: Commit**

```bash
git add simulator tests/sim docs/simulador.md
git commit -m "feat(sim): motoqueiro de mentira fica bloqueado por dívida, paga e volta a trabalhar"
```

---

### Task 6: Fechamento

- [ ] **Step 1: Suíte inteira e banco de desenvolvimento.** `.venv/bin/python -m pytest -q -p no:cacheprovider` (tudo verde), `.venv/bin/alembic upgrade head` e `.venv/bin/alembic current` (mostra `0007 (head)`), e `PYTHONPATH=. .venv/bin/python scripts/smoke_server.py` termina bem.
- [ ] **Step 2: Roteiro e memória.** Marcar o plano 4D como feito; registrar que o limite da dívida agora é uma taxa (R$ 0,70) e o que sobrou (itens abaixo).
- [ ] **Step 3: Commit.**

```bash
git add docs
git commit -m "docs: roteiro com o plano 4D entregue"
```

## Itens que podem sobrar (registrar no roteiro se ocorrerem)

- Devedores e dívida de cada motoqueiro no painel (plano 4A).
- Mais de uma corrida de folga, se o Levy quiser (é só subir `cash_debt_limit_cents`).
- Saldo pré-pago do motoqueiro (depende do advogado).
