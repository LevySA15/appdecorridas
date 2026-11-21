# Nome, perfil e histórico do passageiro — plano de implementação

> **Para quem executa:** use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans, tarefa por tarefa.
> Os passos usam caixas `- [ ]`.

**Objetivo:** o passageiro informa o nome antes de usar o app, tem uma tela de perfil e vê o histórico das corridas encerradas com recibo.

**Arquitetura:** o servidor ganha `name` e `phone` no `GET /v1/passenger/state` e a rota nova `GET /v1/passenger/rides` (sem migração: tudo já
está gravado). O pacote `corrida_core` ganha os modelos e a chamada; o app do passageiro ganha três telas "burras" (nome, perfil, histórico
com recibo), com a navegação toda em `app.dart`, como as telas existentes.

**Tecnologias:** Python 3.12 + FastAPI + SQLAlchemy + pytest (pasta `server/`); Dart/Flutter, pub workspace em `mobile/`.

**Desenho:** `docs/superpowers/specs/2026-11-21-nome-perfil-e-historico-do-passageiro-design.md`

## Restrições globais

- Textos das telas em português do Brasil, simples; dinheiro sempre por `brl(cents)` (`corrida_core`); nenhum dinheiro em `double`.
- Telas só recebem dados e callbacks: nada de `Navigator` nem import de `corrida_core` API/`PassengerController` dentro de `lib/screens/`
  (modelos de `corrida_core` podem ser importados).
- Nome: 2 a 120 letras depois de `trim()` (a regra que o servidor já tem em `AuthService.set_name`).
- Sem migração de banco; sem mudança em regra de pagamento, taxa, cancelamento ou estado de corrida.
- Cada tarefa termina com os testes dela verdes e um commit. Mensagens de commit em português, terminando com a linha
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Flutter nesta máquina: `export PATH="$HOME/development/flutter/bin:$PATH"` em cada comando. Antes de qualquer rodada longa, `free -m`
  (a máquina tem 7 GB; se `disponível` < 1500, esperar). Nunca iniciar uma segunda rodada de pytest enquanto outra roda (mesmo Redis db 15).

## Foco da revisão

Entradas que a spec deixa em silêncio e que mais provavelmente quebram, com a tarefa que as testa:

1. Nome só com espaços (`"   "`) vale como vazio: o app continua na tela do nome (Tarefa 4).
2. Nome de 1 letra ou de 121 letras: o app não chama o servidor com 1 letra; com 121 a recusa do servidor aparece e a tela continua (Tarefa 4).
3. Corrida cancelada antes de alguém aceitar não tem motoqueiro (`rider: null`): servidor e app não quebram e o recibo não mostra "Total" (Tarefas 2 e 5).
4. Endereço de 200 caracteres na lista e no recibo não estoura a tela (Tarefa 5).
5. Falha de rede ao pedir a segunda página: a primeira continua na tela e o botão "Ver mais" volta a funcionar (Tarefa 5).

---

### Task 1: servidor — nome e telefone no estado do passageiro

**Arquivos:**
- Modificar: `server/app/api/views.py` (função `passenger_state`)
- Teste: `server/tests/api/test_passenger_routes.py`

**Interfaces:**
- Produz: `GET /v1/passenger/state` passa a devolver `"name": str` (vazio se ainda não definido) e `"phone": str` (formato `+5575…`).

- [ ] **Passo 1: testes que falham.** Em `test_passenger_routes.py`: (a) no dicionário esperado de `test_estado_do_passageiro_sem_corrida` acrescentar
  `"name": "Ana Lima", "phone": pax.phone`; (b) novo teste:

```python
def test_passageiro_sem_nome_recebe_nome_vazio_no_estado(client, runtime):
    novo = login(client, runtime, "75 99999-0007", "passenger")          # sem name=
    estado = client.get("/v1/passenger/state", headers=novo.headers).json()
    assert estado["name"] == "" and estado["phone"] == novo.phone
```

- [ ] **Passo 2:** `cd server && .venv/bin/pytest tests/api/test_passenger_routes.py -q` → os dois falham (`KeyError`/dicionário diferente).
- [ ] **Passo 3:** em `passenger_state` ler o `UserRow` do passageiro (`session.get(UserRow, passenger_id)`, já importado no arquivo) e acrescentar as duas
  chaves ao dicionário devolvido.
- [ ] **Passo 4:** repetir o comando do passo 2 → passa. Depois `.venv/bin/pytest tests/api -q -x`; se algum teste de outro arquivo comparar o
  dicionário inteiro do estado, ajustá-lo do mesmo jeito (acrescentar as duas chaves).
- [ ] **Passo 5:** commit `feat(servidor): nome e telefone no estado do passageiro`.

---

### Task 2: servidor — histórico de corridas do passageiro

**Arquivos:**
- Modificar: `server/app/db/queries.py` (função nova no fim da seção de passageiro), `server/app/api/views.py`, `server/app/api/routes/passenger.py`
- Modificar: `docs/api-v1.md` (linha nova na tabela do passageiro, depois de `GET /v1/passenger/state`)
- Criar: `server/tests/api/test_passenger_history_routes.py`
- Modificar: `server/tests/api/test_cancel_fee_routes.py` (dois testes no fim), `server/tests/api/test_passenger_routes.py` (lista de rotas só do passageiro)

**Interfaces:**
- Produz (`queries.py`): `passenger_ride_history(session: Session, passenger_id: str, limit: int, offset: int) -> list[dict]`. Devolve as corridas do
  passageiro cujo `state` está em `_TERMINAL` (já definido no arquivo), da mais nova para a mais antiga (`RideRow.created_at.desc(), RideRow.id.desc()`),
  uma consulta só, com `outerjoin` para o motoqueiro (`UserRow` com `aliased` + `RiderProfileRow`), para `CancelFeeRow` (por `ride_id`) e para `RatingRow`
  (`ride_id` igual e `from_user == passenger_id`). Cada item tem exatamente estas chaves:
  `ride_id`, `state` (`completed|cancelled|no_rider`), `created_at` (float, `row.created_at.timestamp()`), `price_cents`,
  `method` (`"balance"` se `pay_with_balance`, senão o `payment_method` da corrida: `pix|cash`), `pickup_text`, `destination_text` (`""` se nulo),
  `distance_m` (`0` se nulo), `rider` (`{"name","plate","moto_model"}` ou `None` quando `rider_id` é nulo), `my_stars` (int ou `None`),
  `fee_cents` (`0` sem taxa), `fee_refunded` (`appeal_state == "accepted"`), `payment_pending` (`state == "completed"` e `method == "cash"` e não
  `end_payment_confirmed`).
- Produz (`views.py`): `passenger_history(unit: Unit, passenger_id: str, limit: int, offset: int) -> dict` = `{"rides": [...], "has_more": bool}`; chama a
  query com `limit + 1` e corta.
- Produz (rota): `GET /v1/passenger/rides?limit=20&offset=0`, `limit` de 1 a 50 e `offset >= 0` (`Query(20, ge=1, le=50)`, `Query(0, ge=0)`, como em
  `routes/admin.py`), só `passenger_user`.

- [ ] **Passo 1: testes que falham** em `test_passenger_history_routes.py` (mesmo `pax`, `cotar`, `pedir`, `login`, `online_rider`, `add_completed_ride` de
  `test_passenger_routes.py`; copiar o fixture `pax`):

```python
def historico(client, quem, **params):
    return client.get("/v1/passenger/rides", params=params, headers=quem.headers)

def test_sem_corridas_o_historico_vem_vazio(client, pax):
    assert historico(client, pax).json() == {"rides": [], "has_more": False}

def test_corrida_concluida_traz_recibo_completo(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX, price=550)
    client.post("/v1/rides/ride-9/rating", json={"stars": 4}, headers=pax.headers)
    item = historico(client, pax).json()["rides"][0]
    assert item["ride_id"] == "ride-9" and item["state"] == "completed" and item["price_cents"] == 550
    assert item["method"] == "pix" and item["my_stars"] == 4 and item["fee_cents"] == 0
    assert item["fee_refunded"] is False and item["payment_pending"] is False
    assert item["rider"] == {"name": f"Motoqueiro {rider_id}", "plate": "ABC0001", "moto_model": item["rider"]["moto_model"]}
    assert isinstance(item["created_at"], float)

def test_corrida_cancelada_sem_motoqueiro_nao_tem_ficha(client, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    assert client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers).status_code == 200
    item = historico(client, pax).json()["rides"][0]
    assert item["state"] == "cancelled" and item["rider"] is None and item["my_stars"] is None
    assert item["pickup_text"] == "Rua A" and item["destination_text"] == "Feira livre"

def test_corrida_aberta_e_corrida_dos_outros_nao_entram(client, runtime, pax, session, clock):
    pedir(client, pax, cotar(client, pax)["quote_id"])                       # aberta
    rider_id = online_rider(session, runtime, clock)
    outra = login(client, runtime, "75 99999-0005", "passenger")
    add_completed_ride(session, "ride-7", outra.user_id, rider_id, PaymentMethod.PIX)
    assert historico(client, pax).json()["rides"] == []

def test_dinheiro_nao_pago_e_pagamento_com_saldo(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-1", pax.user_id, rider_id, PaymentMethod.CASH)
    add_completed_ride(session, "ride-2", pax.user_id, rider_id, PaymentMethod.PIX)
    session.get(RideRow, "ride-2").pay_with_balance = True
    session.flush()
    por_id = {i["ride_id"]: i for i in historico(client, pax).json()["rides"]}
    assert por_id["ride-1"]["payment_pending"] is True and por_id["ride-1"]["method"] == "cash"
    assert por_id["ride-2"]["method"] == "balance" and por_id["ride-2"]["payment_pending"] is False

def test_paginacao_mais_nova_primeiro_e_has_more(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    for n in (1, 2, 3):
        add_completed_ride(session, f"ride-{n}", pax.user_id, rider_id, PaymentMethod.PIX)
    primeira = historico(client, pax, limit=2).json()
    assert [i["ride_id"] for i in primeira["rides"]] == ["ride-3", "ride-2"] and primeira["has_more"] is True
    segunda = historico(client, pax, limit=2, offset=2).json()
    assert [i["ride_id"] for i in segunda["rides"]] == ["ride-1"] and segunda["has_more"] is False

@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"limit": "x"}])
def test_limite_e_deslocamento_invalidos_sao_422(client, pax, params):
    assert historico(client, pax, **params).status_code == 422
```

  Em `test_cancel_fee_routes.py` (usa `cancelar_tarde`, `rider`, `admin`, `pax` do próprio arquivo): `test_historico_mostra_a_taxa_do_cancelamento_tardio`
  (cancelar tarde; o item do histórico tem `fee_cents == resposta["fee_cents"]` > 0 e `fee_refunded is False`) e
  `test_historico_marca_a_taxa_devolvida_quando_o_recurso_e_aceito` (seguir o fluxo de `test_recurso_pela_api_e_decisao_do_administrador`; depois da
  decisão `accepted` o item tem `fee_refunded is True`). Em `test_passenger_routes.py`, na tupla de `test_rotas_do_passageiro_sao_so_do_passageiro`
  acrescentar `("get", "/v1/passenger/rides")` (motoqueiro 403, sem login 401).

- [ ] **Passo 2:** `cd server && .venv/bin/pytest tests/api/test_passenger_history_routes.py tests/api/test_cancel_fee_routes.py tests/api/test_passenger_routes.py -q` → falham (rota 404/405).
- [ ] **Passo 3:** implementar `passenger_ride_history`, `passenger_history` e a rota (assinaturas acima; a rota fica em `passenger.py` junto de `/state`).
- [ ] **Passo 4:** repetir o passo 2 → passam. Depois `.venv/bin/pytest tests/api -q` inteiro.
- [ ] **Passo 5:** documentar a rota em `docs/api-v1.md` (linha da tabela: parâmetros, formato `{"rides","has_more"}`, lista das chaves do item, "só encerradas") e as chaves
  `name`/`phone` na linha do `GET /v1/passenger/state`.
- [ ] **Passo 6:** commit `feat(servidor): histórico de corridas do passageiro`.

---

### Task 3: `corrida_core` — modelos e chamada do histórico, nome no estado

**Arquivos:**
- Modificar: `mobile/packages/corrida_core/lib/src/models/passenger.dart`, `mobile/packages/corrida_core/lib/src/passenger_api.dart`
- Testes: `mobile/packages/corrida_core/test/passenger_models_test.dart`, `.../test/passenger_api_test.dart`, `.../test_contract/contract_test.dart`

**Interfaces:**
- Produz: `PassengerState.name: String` e `PassengerState.phone: String` (padrão `''`; `fromJson` lê `name` e `phone`).
- Produz: `class HistoryRider { final String name, plate, motoModel; }`.
- Produz: `class RideHistoryItem { final String rideId; final RideState state; final double createdAt; final int priceCents; final String method; final String pickupText, destinationText; final int distanceM; final HistoryRider? rider; final int? myStars; final int feeCents; final bool feeRefunded, paymentPending; }` com `factory RideHistoryItem.fromJson(Json)`.
- Produz: `class RideHistoryPage { final List<RideHistoryItem> rides; final bool hasMore; }` com `fromJson`.
- Produz: `Future<RideHistoryPage> PassengerApi.history({int limit = 20, int offset = 0})` → `GET /v1/passenger/rides?limit=&offset=`.

- [ ] **Passo 1: testes que falham.** `passenger_models_test.dart`: `PassengerState.fromJson({'name': 'Ana', 'phone': '+5575999990001'})` lê os dois;
  sem as chaves, `name == ''`; `RideHistoryPage.fromJson` com um item completo (todas as chaves do desenho) e outro cancelado com `rider: null` e
  `my_stars: null` → `rides[1].rider == null`, `rides[1].state == RideState.cancelled`, `hasMore` lido. `passenger_api_test.dart`: `history(limit: 5, offset: 10)`
  faz `GET /v1/passenger/rides` com `limit=5` e `offset=10` na consulta e devolve a página lida (seguir o estilo de `mundo(...)` e `Chamada` do arquivo;
  conferir o caminho em `chamadas.single.path` e os parâmetros em `r.url.queryParameters` dentro do `responde`).
- [ ] **Passo 2:** `cd mobile/packages/corrida_core && dart test test/passenger_models_test.dart test/passenger_api_test.dart` → falham (símbolos inexistentes).
- [ ] **Passo 3:** implementar os modelos (tolerantes como os vizinhos: `asString`, `asInt`, `asBool`, `mapOrNull`, `mapList`) e `history`.
- [ ] **Passo 4:** mesmo comando → passam; `dart test` inteiro do pacote; `flutter analyze` no pacote limpo.
- [ ] **Passo 5: contrato.** Em `test_contract/contract_test.dart`: no teste `'4. corrida paga com Pix…'`, depois das duas avaliações, acrescentar
  `final historico = await passageiro.history(); expect(historico.rides.first.rideId, corrida.rideId); expect(historico.rides.first.state, RideState.completed); expect(historico.rides.first.myStars, 5); expect(historico.rides.first.rider!.name, isNotEmpty);`
  e, no teste `'9. auditoria…'`, o par `'GET /v1/passenger/rides': RideHistoryPage.fromJson` no mapa `parsers`.
  Rodar `cd mobile && tool/contrato.sh` (confere `free -m` antes) → passa; a auditoria também cobra as chaves novas `name`/`phone` do `state`.
- [ ] **Passo 6:** commit `feat(core): modelos e chamada do histórico; nome e telefone no estado`.

---

### Task 4: app do passageiro — nome obrigatório e perfil

**Arquivos:**
- Criar: `mobile/apps/passenger/lib/screens/name_screen.dart`, `mobile/apps/passenger/lib/screens/profile_screen.dart`
- Modificar: `mobile/apps/passenger/lib/passenger_controller.dart`, `.../lib/app.dart`, `.../lib/screens/home_screen.dart`, `.../lib/screens/wallet_screen.dart`
- Testes: criar `.../test/screens/name_screen_test.dart`, `.../test/screens/profile_screen_test.dart`; modificar `.../test/screens/wallet_screen_test.dart`,
  `.../test/screens/home_screen_test.dart`, `.../test/app_test.dart`, `.../test/passenger_controller_test.dart`

**Interfaces:**
- Consome (Tarefa 3): `PassengerState.name`, `PassengerState.phone`, `EmergencyContact`.
- Produz (controller): `Future<void> PassengerController.setName(String name)` — `authApi.updateName(name)` e depois `refreshState()`.
- Produz: `NameScreen({required Future<void> Function(String name) onSave, required VoidCallback onSignOut})`: título "Como podemos te chamar?", campo
  `Key('nome')` com rótulo "Seu nome", botão "Continuar", botão "Sair". Com o nome (`trim`) fora de 2..120 letras mostra o texto
  `Digite seu nome (de 2 a 120 letras).` e **não** chama `onSave`; erro de `onSave` (`ApiException`/`NetworkException`) vira `SnackBar` e a tela continua.
- Produz: `ProfileScreen({required PassengerState state, required Future<void> Function(String name) onSaveName, required Future<void> Function(String name, String phone) onSetEmergencyContact, required VoidCallback onSignOut})`:
  mostra o telefone (`state.phone`, só leitura, `Key('perfil_telefone')`), campo do nome `Key('perfil_nome')` + "Salvar nome", o contato de emergência com os campos
  `Key('contato_nome')` / `Key('contato_telefone')` e "Salvar" (mesmas chaves que a carteira usa hoje) e o botão "Sair".
- Produz: `HomeScreen` ganha `onOpenProfile` e `onOpenHistory` (`VoidCallback`, obrigatórios) e duas linhas "Minhas corridas" e "Perfil" entre o saldo e o "Sair".
- Muda: `WalletScreen` perde `onSetEmergencyContact`, os dois controladores e o bloco "Contato de emergência" (e o teste que o cobria passa para o perfil).
- Muda (`app.dart`): na raiz do `Navigator`, se `state.name.trim().isEmpty` mostra `NameScreen` no lugar do `HomeScreen`; rotas novas `_openProfile()`
  (empilha `ProfileScreen` dentro de `ListenableBuilder(listenable: controller)` como a carteira) e `_openHistory()` (Tarefa 5).

- [ ] **Passo 1: testes que falham.**
  - `name_screen_test.dart`: (a) nome `"Ana Lima"` + "Continuar" chama `onSave('Ana Lima')`; (b) `"   "` e `"A"` mostram o texto de erro e `onSave` não é chamado;
    (c) `onSave` que lança `ApiException(...)` mostra a mensagem num `SnackBar` e o campo continua na tela (use o construtor de `ApiException` como em `wallet_screen_test.dart`/`home_screen_test.dart`).
  - `profile_screen_test.dart`: mostra o telefone; "Salvar nome" chama `onSaveName` com o texto; o contato de emergência preenchido a partir do estado e "Salvar"
    chama `onSetEmergencyContact` (mover daqui o teste `salvar contato de emergencia…` de `wallet_screen_test.dart`); "Sair" chama `onSignOut`.
  - `app_test.dart`: `Mundo.stateJson` passa a ter `'name': 'Ana'` por padrão e os outros `stateJson = {...}` do arquivo (os de ≈ linhas 197 e 225) ganham a mesma chave;
    novos testes: (d) estado com `'name': ''` mostra `NameScreen` e **não** `HomeScreen`; (e) `'name': '   '` também; (f) salvar o nome chama `PUT /v1/me` com
    `{"name": "Ana"}` (acrescentar o tratador no `Mundo._handle`: ele devolve `{'user_id':'u1','phone':'+5575','name':'Ana','role':'passenger'}` e já troca
    `stateJson` para `{'name': 'Ana'}`, para a releitura seguinte vir com o nome) e depois aparece o `HomeScreen`.
  - `home_screen_test.dart`: tocar "Minhas corridas" chama `onOpenHistory`, "Perfil" chama `onOpenProfile` (acrescentar os dois parâmetros ao `_screen()` de apoio).
  - `passenger_controller_test.dart`: `setName('Ana')` faz `PUT /v1/me` e relê o estado (`GET /v1/passenger/state`).
- [ ] **Passo 2:** `export PATH="$HOME/development/flutter/bin:$PATH"; cd mobile/apps/passenger && flutter test test/screens test/app_test.dart test/passenger_controller_test.dart` → falham.
- [ ] **Passo 3:** implementar na ordem: controller → `NameScreen` → `ProfileScreen` → retirar o bloco da carteira → `HomeScreen` → `app.dart`.
- [ ] **Passo 4:** `flutter test` inteiro do app e `flutter analyze` limpo. O teste `android_manifest_test.dart` deve continuar passando.
- [ ] **Passo 5:** commit `feat(passageiro): nome obrigatório e tela de perfil`.

---

### Task 5: app do passageiro — histórico e recibo

**Arquivos:**
- Criar: `mobile/apps/passenger/lib/format.dart`, `mobile/apps/passenger/lib/screens/history_screen.dart`, `mobile/apps/passenger/lib/screens/receipt_screen.dart`
- Modificar: `mobile/apps/passenger/lib/passenger_controller.dart`, `mobile/apps/passenger/lib/app.dart`
- Testes: criar `.../test/format_test.dart`, `.../test/screens/history_screen_test.dart`, `.../test/screens/receipt_screen_test.dart`; modificar `.../test/app_test.dart`

**Interfaces:**
- Consome (Tarefa 3): `RideHistoryPage`, `RideHistoryItem`, `PassengerApi.history`.
- Produz (controller): `Future<RideHistoryPage> PassengerController.loadHistory({int offset = 0})` → `api.history(limit: 20, offset: offset)`.
- Produz (`format.dart`): `String formatRideDate(double epochSeconds)` → `dd/mm/aaaa HH:mm` na hora local do aparelho (`DateTime.fromMillisecondsSinceEpoch((s * 1000).round())`).
- Produz (`format.dart`): `String rideStateLabel(RideState state)` → `completed` "Concluída", `cancelled` "Cancelada", `noRider` "Sem moto", outro "Encerrada".
- Produz: `HistoryScreen({required Future<RideHistoryPage> Function(int offset) onLoad, required void Function(RideHistoryItem) onOpenReceipt})`: carrega a primeira
  página ao abrir; lista com data, estado, "origem → destino" (uma linha cada, `maxLines: 1`, `overflow: TextOverflow.ellipsis`) e o preço só nas concluídas; botão "Ver mais" enquanto
  `hasMore` (pede `offset = itens já na tela`); estado vazio "Você ainda não fez corridas."; falha na primeira página mostra a frase do erro e "Tentar de novo"; falha numa página seguinte mostra um
  `SnackBar` e mantém os itens já carregados.
- Produz: `ReceiptScreen({required RideHistoryItem ride})`: data, estado, origem, destino, distância em km (uma casa), motoqueiro (nome, placa, modelo) quando houver, forma de pagar
  ("Pix", "Dinheiro", "Saldo do app"), nota que o passageiro deu (`my_stars` de 5) quando houver; **só nas concluídas** a linha "Total" com `brl(priceCents)` (e "Pagamento pendente" se `paymentPending`);
  nas canceladas/sem moto, se `feeCents > 0` a linha "Taxa de cancelamento" com `brl(feeCents)` e, se `feeRefunded`, o texto "devolvida".
- Muda (`app.dart`): `_openHistory()` empilha `HistoryScreen`; tocar num item empilha `ReceiptScreen`.

- [ ] **Passo 1: testes que falham.**
  - `format_test.dart`: `formatRideDate` de um instante fixo (construir com `DateTime(2026, 11, 20, 18, 5).millisecondsSinceEpoch / 1000`) devolve `'20/11/2026 18:05'`; `rideStateLabel` dos três estados.
  - `history_screen_test.dart`: (a) página com 2 itens mostra os dois e não mostra "Ver mais" quando `hasMore` é falso; (b) `hasMore: true` mostra "Ver mais", tocar chama `onLoad(2)` e acrescenta os itens da segunda página;
    (c) lista vazia mostra "Você ainda não fez corridas."; (d) `onLoad` que lança na primeira vez mostra "Tentar de novo" e, ao tocar, carrega; (e) falha na segunda página mantém a primeira e mostra `SnackBar` (foco 5);
    (f) endereço de 200 caracteres: `tester.takeException()` é `null` (foco 4); (g) tocar num item chama `onOpenReceipt` com ele.
  - `receipt_screen_test.dart`: concluída mostra "Total", motoqueiro e nota; cancelada sem motoqueiro (`rider == null`) **não** mostra "Total" nem ficha e não quebra (foco 3); cancelada com taxa 350 mostra "Taxa de cancelamento" e `brl(350)`; com `feeRefunded` mostra "devolvida"; `paymentPending` mostra "Pagamento pendente"; endereço de 200 caracteres sem exceção (foco 4).
  - `app_test.dart`: a partir da Home, tocar "Minhas corridas" abre o `HistoryScreen` e chama `GET /v1/passenger/rides` (tratador novo no `Mundo._handle` devolvendo `{'rides': [...], 'has_more': false}`).
- [ ] **Passo 2:** `export PATH="$HOME/development/flutter/bin:$PATH"; cd mobile/apps/passenger && flutter test test/format_test.dart test/screens/history_screen_test.dart test/screens/receipt_screen_test.dart test/app_test.dart` → falham.
- [ ] **Passo 3:** implementar `format.dart`, controller, `HistoryScreen`, `ReceiptScreen` e a navegação.
- [ ] **Passo 4:** `flutter test` inteiro do app e `flutter analyze` limpo.
- [ ] **Passo 5:** commit `feat(passageiro): histórico de corridas e recibo`.

---

### Task 6: verificação final e roteiro

**Arquivos:**
- Modificar: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md` (seção nova "Itens que sobraram do plano 6C", antes de "Itens que sobraram do plano 3")

- [ ] **Passo 1:** `free -m`; depois, em primeiro plano e uma rodada só: `cd server && .venv/bin/pytest tests -q -x --ignore=tests/sim` e, na sequência, `.venv/bin/pytest tests/sim -q` (a suíte do
  simulador lê o estado do passageiro; leva alguns minutos). Esperado: tudo verde.
- [ ] **Passo 2:** `cd mobile/packages/corrida_core && dart test`; `cd ../corrida_ui && flutter test`; `cd ../../apps/passenger && flutter test && flutter analyze`; `cd ../rider && flutter test` (o app do
  motoqueiro não deve mudar); `cd ../.. && tool/contrato.sh`. Esperado: tudo verde.
- [ ] **Passo 3:** o APK de debug do passageiro compila: `cd mobile/apps/passenger && flutter build apk --debug` (precisa das licenças do Android; se faltarem, anotar no roteiro em vez de contornar).
- [ ] **Passo 4:** escrever no roteiro: o que foi feito, as suítes e contagens, o que **não** foi visto num celular (nome, perfil, histórico), e as decisões do desenho (contato de emergência mudou de lugar; recibo sem dados
  do motoqueiro além de nome/placa/modelo; nome só obrigatório no app).
- [ ] **Passo 5:** commit `docs: roteiro do plano 6C`.
