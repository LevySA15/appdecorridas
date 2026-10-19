# API do servidor, versão 1

Contrato que os apps (planos 5 e 6), o painel (plano 4) e o simulador (plano 3) usam. Em modo de desenvolvimento
(`APP_MODE=dev`) o servidor também publica a descrição gerada automaticamente em `/docs` e `/openapi.json`.

## Convenções

- Tudo em `/v1`, JSON em UTF-8. Entrar: `Authorization: Bearer <token>` em toda rota, menos as de login e o aviso do provedor.
- **Dinheiro em centavos inteiros.** Horas em segundos Unix (`float`). Datas `AAAA-MM-DD`. Coordenadas `{"lat", "lng"}`.
- Erro: `{"error": {"code": "...", "message": "..."}}` (às vezes com `field` ou `fields`). O app decide pelo `code`,
  que é estável; a `message` é uma frase em português para mostrar à pessoa.
- Cada papel só usa as suas rotas: `passenger`, `rider` ou `admin` (`403 wrong_role` nas outras).
- Os avisos em tempo real (WebSocket) são **dicas**. A fonte da verdade é `GET /v1/passenger/state` e
  `GET /v1/rider/state`: ao abrir o app, ao reconectar e ao receber `ready`, peça o estado de novo.

## Entrar e conta

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /v1/auth/code` | `{"phone"}` | 204. Envia o código de 6 dígitos (WhatsApp no plano 7). 429 se pediu demais. |
| `POST /v1/auth/verify` | `{"phone","code","role","device"?}` | `{"token","user_id","role","is_new_user","name"}`. 401 `code_invalid` com a frase do motivo. |
| `POST /v1/auth/logout` | | 204 |
| `GET /v1/me` | | `{"user_id","phone","name","role"}` |
| `PUT /v1/me` | `{"name"}` | o mesmo de `GET /v1/me` |

A sessão dura 180 dias. `role: "admin"` só entra se o número já foi criado com `python -m app.cli create-admin`.

## Passageiro

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /v1/passenger/quotes` | `{"pickup": {lat,lng,text}, "destination": {lat,lng,text}}` | preço: `quote_id, price_cents, reason, distance_m, duration_s, expires_at, pickup, destination, eta_seconds` (estimativa, `null` sem moto livre), `nearby_riders`, `payment_methods` (`["pix","cash"]`, ou só `["cash"]` com o Pix fora do ar) |
| `POST /v1/passenger/rides` | `{"quote_id","method": "pix"\|"cash"}` | 201 com a corrida (abaixo) |
| `POST /v1/passenger/rides/{id}/cancel` | | `{"refund", "fee_cents", "fee", "refund_to", "balance_cents"}` (veja "Cancelamento tardio" abaixo) |
| `POST /v1/passenger/fees/pay` | | paga a taxa de cancelamento pendente: `{"paid": true}` se o saldo cobriu tudo, senão `{"paid": false, "charge_id","amount_cents","br_code"}` (Pix do valor inteiro). 409 `nothing_to_pay` |
| `POST /v1/passenger/rides/{id}/fee/appeal` | `{"text"}` (3 a 500 letras) | 204. 404 sem taxa; 403 `not_your_ride`; 409 `appeal_not_allowed` (já pedido ou passou de 7 dias) |
| `POST /v1/passenger/balance/topup` | `{"amount_cents"}` | `{"charge_id","amount_cents","br_code"}`. 403 `topup_disabled` (desligada por padrão); 422 fora de R$ 10,00 a R$ 200,00 |
| `GET /v1/passenger/state` | | `{"ride", "pending_payment", "blocked_reason", "unpaid_cents", "balance_cents", "topup_enabled", "pending_fee", "recent_fees", "emergency_contact", "payment_methods"}` |
| `PUT /v1/passenger/emergency-contact` | `{"name","phone"}` | 204. Não pode ser o número do próprio passageiro. |
| `POST /v1/rides/{id}/rating` | `{"stars": 1..5}` | 204 (vale para os dois lados, depois que a corrida acabou) |
| `POST /v1/rides/{id}/sos` | | `{"alert_id","contact_registered","contact_notified","repeated","emergency_number": "190"}` |
| `POST /v1/rides/{id}/safety/{alert_id}/ok` | | 204 ("está tudo bem" ao aviso automático) |

**Corrida (visão do passageiro):** `ride_id, state` (`searching, queued, accepted, arrived, in_progress`),
`queued, price_cents, price_reason, method, pin` (os 4 dígitos que ele diz ao motoqueiro), `helmet_confirmed, pix_paid,
pickup, destination, distance_m, rider` (`rider_id, name, plate, moto_model, rating, rating_count, photo_url`),
`rider_position` (`{lat,lng}` ou `null`), `queue` (`{"finishing_at","eta_seconds"}` quando está na fila),
`safety_alert` (`{"alert_id","kind"}` enquanto o "está tudo bem?" não foi respondido, para redesenhar a tela ao reconectar),
`pay` (`{"charge_id","amount_cents","expires_at"}` enquanto o Pix não foi pago), `end_payment` e `cancel`
(`{"free_until","fee_cents_now"}` com a moto a caminho: até quando cancelar é grátis e quanto custaria cancelar agora; `null` nos outros estados).
`photo_url` é uma rota com login: `GET /v1/riders/{id}/documents/selfie`.

**Cancelamento tardio (taxa de R$ 3,00 a R$ 5,00).** Cancelar é grátis até 5 minutos depois de a moto aceitar (e sempre que a
corrida ainda não tem moto ou está na fila). Depois disso há uma taxa de R$ 3,00 a R$ 5,00, maior quanto mais a moto já
andou (com a moto no ponto, R$ 5,00; sem posição da moto, R$ 3,00). Passageiro que não aparece depois de 5 minutos de espera na
chegada paga R$ 5,00. A taxa vai inteira para o motoqueiro e é cobrada nesta ordem: do **saldo** do passageiro, depois da
**devolução do Pix** já pago (a moto fica com a taxa e só o resto volta), e o que sobrar vira **pendência**: o passageiro não pede outra
corrida até pagar (`blocked_reason`). Resposta do cancelamento: `fee_cents` (0 se foi de graça), `fee`
(`{"from_balance_cents","retained_cents","pending_cents"}` ou `null`), `refund` (havia Pix pago), `refund_to`
(`"pix"`, `"balance"` quando a devolução não chegou à chave Pix do passageiro e virou saldo, ou `null`) e `balance_cents` (saldo depois).

`pending_fee` (no estado): `{"ride_id","amount_cents","charge_id","appeal"}`, com `charge_id` quando já existe um Pix aberto para pagar a
pendência. `recent_fees` traz as últimas 5 taxas dentro do prazo do recurso: `{"ride_id","fee_cents","created_at","from_balance_cents","retained_cents","pending_cents","appeal_state","can_appeal"}`
(`appeal_state`: `none`, `open`, `accepted` ou `rejected`). O **recurso** vale por 7 dias, uma vez por taxa; enquanto é analisado a taxa
continua cobrada. Aceito: a pendência é perdoada e o que já foi cobrado volta como saldo (a empresa paga; o motoqueiro fica com a taxa).

**Saldo** (`balance_cents`): dinheiro do passageiro guardado no app. Recebe a devolução que não chegou à chave Pix e, com a recarga
ligada (`topup_enabled`), recargas por Pix. Por enquanto só paga a taxa de cancelamento.

`pending_payment` (corrida em dinheiro terminada e sem pagamento): `{"ride_id","amount_cents","charge_id","blocked"}`.
Com `blocked: true` o passageiro não pede outra corrida até pagar o QR (`charge_id`).

**Alerta de "muito tempo sem sinal" (`kind: "no_signal"`).** Com a corrida em andamento, se a moto fica sem mandar posição por
mais que o limite do tamanho da corrida (até 3 km: 2 minutos; de 3 a 10 km: 4 minutos; acima de 10 km: 6 minutos; tabela
provisória do Levy, depois vira um algoritmo de distância), o servidor avisa **o passageiro** (`safety_check` com
`kind: "no_signal"`, que ele responde como os outros em `POST /v1/rides/{id}/safety/{alert_id}/ok`), **o contato de emergência**
dele (WhatsApp, plano 7) e **os administradores** (`safety_alert`, e o alerta aparece em `GET /v1/admin/safety-alerts`). Repete
só depois de 10 minutos de silêncio que continua.

## Cobrança (QR do Pix)

`GET /v1/charges/{charge_id}` → `{"charge_id","purpose","ride_id","amount_cents","paid","br_code"}`.
`purpose`: `ride` (Pix antes da corrida), `end` (QR do fim da corrida em dinheiro), `entry` (entrada do motoqueiro),
`fee` (taxa de cancelamento pendente), `topup` (recarga do saldo, `ride_id` nulo) ou `debt` (dívida da taxa do motoqueiro, `ride_id` nulo; só o motoqueiro dono e o administrador veem).
O app desenha o QR a partir de `br_code`. Vê quem participa da corrida (passageiro e motoqueiro) e o administrador;
a entrada, só o motoqueiro; a recarga, só o passageiro dono.

## Motoqueiro

| Rota | Corpo | Resposta |
|---|---|---|
| `PUT /v1/rider/documents/{selfie\|cnh\|crlv}` | a foto crua (JPEG, PNG ou WebP, até 8 MB) | 201 `{"key","bytes"}` |
| `POST /v1/rider/register` | nome, CPF, CNH, placa, modelo, validade da CNH e do documento da moto, `selfie_key`, `cnh_photo_key`, `crlv_key` | 201 `{"status":"pending"}` |
| `POST /v1/rider/documents/renew` | `{"cnh_expires_on","crlv_expires_on","cnh_photo_key"?,"crlv_key"?}` | 204 |
| `GET /v1/rider/state` | | `{"registration","account","offer","ride","queued_ride","awaiting_payment"}`. `account` traz também `blocked_reason` (`"entry_pending"`, `"debt_pending"` ou `null`), `cash_debt_cents`, `cash_debt_limit_cents` (uma taxa: R$ 0,70) e `debt_to_pay_cents` |
| `POST /v1/rider/online` · `/offline` | | 204. 409 com o `code` do motivo (`not_approved`, `blocked`, `documents_expired`, `entry_pending`, `debt_pending`) |
| `POST /v1/rider/position` | `{"lat","lng"}` | 204. A cada ~4 s enquanto disponível (e durante a corrida). |
| `POST /v1/rider/entry-charge` | | 201 `{"charge_id","amount_cents","br_code"}` (a entrada de R$ 50) |
| `POST /v1/rider/debt-charge` | | 201 `{"charge_id","amount_cents","br_code"}` (a dívida da taxa das corridas em dinheiro; 409 `invalid_state` se não deve nada) |
| `POST /v1/rider/offers/{ride_id}/accept` | | a corrida (visão do motoqueiro) |
| `POST /v1/rider/offers/{ride_id}/decline` | | 204, sem penalidade |
| `POST /v1/rider/rides/{id}/arrive` · `/helmet` · `/complete` | | a corrida |
| `POST /v1/rider/rides/{id}/start` | `{"pin": "1234"}` | a corrida. 422 `wrong_pin`; depois de 5 erros em 10 min, 429. |
| `POST /v1/rider/rides/{id}/cash-received` | | 204 (recebi o dinheiro na mão) |

**Corrida (visão do motoqueiro):** `ride_id, state, queued, price_cents, fee_cents, method, pix_paid, helmet_confirmed,
passenger` (`{"name"}`, só o primeiro nome), `pickup, destination, distance_m` e `end_payment`
(`{"charge_id","amount_cents","blocked"}` enquanto a corrida em dinheiro espera pagamento).

**Estado do motoqueiro:** `registration` (`status`: `not_registered, pending, approved, rejected, blocked`; `online`,
`reason`, `rating`, `rating_count`, validades), `account` (`completed_rides, trial_rides, entry_paid, entry_fee_cents,
needs_entry, cash_debt_cents, cash_debt_limit_cents`), `offer` (a oferta pendente, no mesmo formato do aviso `offer`),
`ride` (andando), `queued_ride` e `awaiting_payment`.

## Documentos

`GET /v1/riders/{rider_id}/documents/{selfie|cnh|crlv}` devolve a imagem. Vê tudo: o administrador e o próprio
motoqueiro. O passageiro vê só a `selfie`, de um motoqueiro que já aceitou uma corrida dele.

## Administrador (a API do painel do dono, `/painel`)

| Rota | |
|---|---|
| `GET /v1/admin/riders?status=pending\|approved\|blocked\|rejected&limit&offset` | fila de cadastros |
| `POST /v1/admin/riders/{id}/approve` · `/unblock` | 204 |
| `POST /v1/admin/riders/{id}/reject` · `/block` | `{"reason"}` → 204 |
| `GET /v1/admin/appeals?status=open\|accepted\|rejected&limit&offset` | recursos da taxa de cancelamento, o mais antigo primeiro: `ride_id, passenger_id, passenger_name, rider_name, fee_cents, reason, created_at, appeal_state, appeal_text, appealed_at, decided_at, decision_note` |
| `POST /v1/admin/appeals/{ride_id}/decide` | `{"decision": "accept"\|"reject", "note"?}` → 204. 409 `appeal_not_allowed` se não está aberto |
| `GET /v1/admin/safety-alerts?status=open\|ok\|sos\|resolved` | alertas com nomes, placa e posição |
| `POST /v1/admin/safety-alerts/{id}/resolve` | `{"note"?}` → 204 |

### Rotas do painel do dono (plano 4A)

Só administrador. Leituras: `GET /v1/admin/rides?state=&limit=&offset=` (corridas, mais novas primeiro, com nomes), `GET /v1/admin/rides/{id}`
(detalhe com `events` e `cancel_fee`; nunca traz o código de 4 dígitos), `GET /v1/admin/passengers?q=` (busca por nome ou telefone: `user_id, name, phone,
is_blocked, unpaid_cents, balance_cents, created_at`), `GET /v1/admin/debtors` (`riders` e `passengers` que devem algo), `GET /v1/admin/money` (totais do
livro-caixa e das contas: `company_cents, provider_cents, riders_cents, passenger_balances_cents, rider_debts_cents, passenger_unpaid_cents,
pending_fees_cents, rides_by_state, ledger_balanced`), `GET /v1/admin/config` (todas as chaves de parâmetros) e `GET /v1/admin/actions?limit&offset`
(registro das ações, mais nova primeiro: `id, admin_id, admin_name, action, target_type, target_id, detail, at`).
Escritas: `POST /v1/admin/passengers/{id}/block` (`{"reason"}`) e `/unblock` → 204; `PUT /v1/admin/config/{key}` (o objeto da chave) → 204, 422 `invalid`
com a frase do erro se o valor não faz sentido, 404 se a chave não existe; vale na hora neste processo. **Toda escrita do administrador** (aprovar,
recusar, bloquear e liberar motoqueiro e passageiro, resolver alerta, decidir recurso, gravar parâmetro) grava uma linha em `admin_actions` na mesma
transação. O site fica em `GET /painel` (HTML e JavaScript, sem dado; os dados vêm destas rotas, com o token do administrador).

## Aviso do provedor de pagamento

`POST /v1/webhooks/pix`, sem login. O corpo é JSON `{"event_id","type":"paid","charge_id","ride_id","amount_cents"}` e
a assinatura vai no cabeçalho `x-signature: sha256=<HMAC-SHA256 do corpo com WEBHOOK_SECRET>`. Resposta
`{"status": "applied"|"refunded"|"duplicate"|"unknown_charge"}`. Valor ou corrida diferentes da cobrança guardada: 409
`event_mismatch` (o aviso não é gasto). O adaptador da Woovi (plano 7) traduz o aviso dela para este formato.

## Só em desenvolvimento (`APP_MODE=dev`)

`GET /v1/dev/otp?phone=...` devolve o último código de login enviado; `POST /v1/dev/pix/{charge_id}/pay` faz de conta
que o passageiro pagou o Pix (passa pelo mesmo caminho do aviso real); `GET /v1/dev/audit` é a conferência de fim de dia que o
simulador pede (`docs/simulador.md`): `{"ledger_balanced", "reconcile_diff", "rides_by_state", "open_rides",
"double_booked_riders", "balance_matches_ledger", "inconsistent_fees"}`, isto é, o livro-caixa fecha, bate com o extrato do provedor falso
(que desconta devoluções parciais), quantas corridas há em cada estado, quais ainda estão abertas, se algum motoqueiro tem duas
corridas ativas, se a soma dos saldos dos passageiros é igual à das contas `balance:*` do livro e quais taxas de cancelamento têm
partes que não somam o valor da taxa (sempre vazio). Em produção estas rotas não existem.

## Tempo real (WebSocket)

Conectar em `/v1/ws`. A **primeira mensagem** é `{"token": "..."}` (o token não vai na URL). Resposta:
`{"type":"ready","data":{"user_id","role"},"at":...}`. Depois chegam avisos `{"type","data","at"}`. Token ruim ou
ausente em 10 s: o servidor fecha com o código **4401**. Fila cheia (o app não está lendo): fecha com **4408**.
Nos dois casos, reconecte e peça o estado. O app pode mandar texto qualquer (`"ping"`) para manter a conexão viva.

| Aviso | Para | `data` |
|---|---|---|
| `offer` | motoqueiro | `ride_id, price_cents, payment_method, pickup, destination, distance_m, seconds_to_pickup, will_queue, expires_at` |
| `offer_expired` | motoqueiro | `ride_id` |
| `ride_assigned` | motoqueiro | `ride_id, queued` |
| `next_ride` | motoqueiro | `ride_id` (a corrida da fila começou) |
| `ride_cancelled` | os dois | `ride_id`, `by: "passenger"` ou `reason: "pix_expired"\|"arrival_wait"`, e `fee_cents` (a taxa de cancelamento tardio; 0 ou ausente se grátis) |
| `rider_accepted` | passageiro | `ride_id, queued, pin, queue, rider, pay` |
| `rider_on_the_way` | passageiro | `ride_id` (a corrida da fila começou) |
| `rider_arrived` · `trip_started` | passageiro | `ride_id` |
| `rider_position` | passageiro | `ride_id, lat, lng` |
| `trip_completed` | os dois | `ride_id, price_cents, method, pay` |
| `no_rider` | passageiro | `ride_id` |
| `queue_released` | passageiro | `ride_id, refunded` |
| `pix_confirmed` | passageiro | `ride_id, amount_cents` |
| `payment_received` | motoqueiro | `ride_id, late` (corrida) ou `ride_id, amount_cents, kind: "cancel_fee"` (taxa de cancelamento paga depois) |
| `payment_refunded` | passageiro | `ride_id, amount_cents, to: "pix"\|"balance"` (e `balance_cents` quando foi para o saldo) |
| `cancel_fee` | passageiro | `ride_id, fee_cents, from_balance_cents, retained_cents, pending_cents, balance_cents` |
| `fee_paid` | passageiro | `ride_id, amount_cents, balance_cents` (a pendência foi paga) |
| `balance_changed` | passageiro | `balance_cents` (recarga) |
| `appeal_opened` | administradores | `ride_id` |
| `appeal_decided` | passageiro | `ride_id, decision: "accept"\|"reject", credited_cents` |
| `qr_ready` | os dois | `ride_id, charge_id, amount_cents` (o QR do fim da corrida em dinheiro) |
| `payment_confirmed` | passageiro | `ride_id` (o motoqueiro confirmou o dinheiro) |
| `payment_pending` | passageiro | `ride_id, amount_cents, charge_id` (passou o prazo sem pagar: pague o QR) |
| `passenger_blocked` | motoqueiro | `ride_id` (o passageiro foi bloqueado; você está livre) |
| `unblocked` | passageiro | `ride_id` |
| `entry_required` · `entry_paid` | motoqueiro | `entry_fee_cents` · sem dados |
| `debt_required` · `debt_paid` | motoqueiro | `cash_debt_cents, debt_limit_cents` (a dívida chegou ao limite: ele foi para "não estou" e não recebe corrida) · `cash_debt_cents, amount_cents` |
| `rider_approved` · `rider_rejected` · `rider_blocked` · `rider_unblocked` · `documents_expired` | motoqueiro | `reason` quando houver |
| `safety_check` | passageiro | `ride_id, alert_id, kind` (`stopped`, `off_route` ou `no_signal`): "está tudo bem?" |
| `sos_sent` | passageiro | `alert_id, contact_registered, contact_notified` |
| `safety_alert` · `safety_ok` · `sos` · `mock_location_suspected` | administradores | dados do alerta e da corrida (`kind`: `stopped`, `off_route`, `no_signal` ou `sos`) |

## Códigos de erro

`appeal_not_allowed` 409 · `debt_pending` 409 · `nothing_to_pay` 409 · `topup_disabled` 403 · `unauthorized` 401 · `wrong_role` 403 · `forbidden` 403 · `not_found` 404 · `invalid` 422 (`fields` lista os campos) ·
`not_allowed` 403 · `quote_expired` 409 · `offer_gone` 409 · `not_your_ride` 403 · `already_rated` 409 ·
`invalid_state` 409 · `alert_closed` 409 · `duplicate_registration` 409 (`field`) · `not_approved`, `blocked`,
`documents_expired`, `entry_pending` 409 · `wrong_pin` 422 · `code_invalid` 401 · `too_many_requests` 429 ·
`payment_unavailable` 503 · `bad_signature` 401 · `event_mismatch` 409 · `file_too_large`/`too_large` 413 ·
`not_an_image` 415 · `empty_file` 422 · `http_404`/`http_405` · `internal` 500.

## Operação

- **Um processo só** (`--workers 1`): o hub do WebSocket e o agendador vivem dentro dele. Mais de um processo precisa de
  um canal entre eles (por exemplo, Redis pub/sub) e de uma trava para o agendador; isso não existe ainda.
- Atrás de um proxy (nginx), suba com `--proxy-headers --forwarded-allow-ips='*'` só se o servidor ficar acessível
  exclusivamente pelo proxy, para o limite de pedidos de código por aparelho enxergar o IP verdadeiro. O proxy também
  deve limitar o tamanho do corpo dos pedidos (as rotas de foto e de aviso já cortam o que passa do limite).
- O servidor recusa subir sem `APP_MODE=dev` até o plano 7 trazer os adaptadores reais.
