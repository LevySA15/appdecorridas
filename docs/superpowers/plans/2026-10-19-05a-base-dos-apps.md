# Base dos apps (pacote `corrida_core`) — Plano de implementação (plano 5A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Começar os planos 5 e 6 (apps do motoqueiro e do passageiro, Flutter) pela parte que os dois dividem e que se prova sem celular: instalar o Flutter, criar a pasta `mobile/` e o pacote Dart `corrida_core` com o cliente da API (`docs/api-v1.md`), as sessões, os modelos e o cliente de tempo real (WebSocket), testado com servidor de mentira **e contra o servidor de verdade**.

**Architecture:** Um espaço de trabalho Dart (`mobile/pubspec.yaml` com `workspace:`) com o pacote `packages/corrida_core` (Dart puro: roda com `dart test`, leve em memória) e, nos planos seguintes, `apps/passageiro` e `apps/motoqueiro` (Flutter). Nada de geração de código: modelos escritos à mão, só `fromJson`/`toJson`. O cliente nunca guarda estado de corrida: o servidor é a fonte da verdade (`GET /v1/*/state`), os avisos do WebSocket são dicas para reler o estado.

**Tech Stack:** Dart 3.13 / Flutter 3.47.7 (estável, 8/10/2026), pacotes `http` 1.x, `web_socket_channel` 3.x, `test` 1.x, `lints`. O servidor Python existente para o teste de contrato.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 4, 9, 10.2, 12) e o contrato `docs/api-v1.md`.

## Global Constraints

- **Dinheiro em centavos inteiros** (`int`) em todo o pacote; texto só na hora de mostrar (`brl`). Horas em segundos Unix (`double`, como o servidor). Coordenadas `{lat, lng}`.
- **Leitura tolerante:** campo que o servidor passar a mandar e o pacote não conhece é ignorado; campo conhecido que falta vira `null`/padrão em vez de derrubar o app; estado de corrida desconhecido vira `RideState.unknown`.
- O token **nunca** vai para a URL nem para o texto de um erro. O WebSocket manda o token na primeira mensagem.
- Erro da API vira `ApiException(status, code, message)`; falta de rede, tempo esgotado ou resposta que não é JSON vira `NetworkException`. O app decide pelo `code` (estável); a `message` está em português e pode ser mostrada.
- O pacote não depende de Flutter (`dart test` basta).
- Comentários e textos para a pessoa em português do Brasil, simples; nomes de código em inglês.
- Todos os comandos Dart/Flutter partem de `mobile/` com `export PATH="$HOME/development/flutter/bin:$PATH"` (o Flutter fica em `~/development/flutter`, fora do repositório e sem mexer no perfil do shell).
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Um comando de git por vez.

## Review Focus

1. **Resposta inesperada do servidor** (corpo vazio, HTML de proxy, JSON sem os campos conhecidos, estado novo): nunca estoura exceção que não seja `ApiException`/`NetworkException`. Tarefas 1, 3, 4.
2. **Reconexão do WebSocket:** não gruda em laço quente quando o servidor fecha com 4401 (token ruim: para e avisa) ou 4408 (fila cheia: reconecta); recua o tempo entre tentativas; ao reconectar avisa para reler o estado; fechar o cliente encerra tudo sem avisos depois. Tarefa 5.
3. **Sessão vencida (401)** no meio do uso: o app é avisado uma única vez e o token é limpo. Tarefas 1 e 2.
4. **Contrato com o servidor real:** uma corrida inteira (passageiro e motoqueiro) pelo cliente Dart contra um servidor de verdade descartável, para o pacote não se afastar da API sem ninguém ver. Tarefa 6.
5. **Foto do documento:** envio de bytes crus com o tipo certo e limite de tamanho do servidor (413) virando erro claro. Tarefa 4.

## Decisões deste plano (o Levy confere)

1. **Flutter instalado em `~/development/flutter` (3.47.7), sem aceitar licenças do Android por você.** Para gerar o aplicativo no celular (plano 6) será preciso rodar `flutter doctor --android-licenses` e aceitar você mesmo; o plano 5A não precisa.
2. **Não há celular nem emulador neste computador** (7 GB de memória, 2 GB livres): a parte visual dos apps será conferida por testes de tela (`flutter test`) e, quando você conectar um celular com depuração USB ou passar o APK, por você.
3. **Os dois apps ficam no mesmo repositório,** na pasta `mobile/`, com este pacote em comum.
4. **Mapa:** o código de mapas fica atrás de uma interface própria nos apps; até o plano 7 (chave do Google Maps) um mapa de mentira desenhado na tela.
5. **Fora deste plano:** telas, armazenamento seguro do token no celular, serviço em primeiro plano de posição do motoqueiro, notificações (Firebase), mapa, tradução de textos.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `mobile/pubspec.yaml`, `mobile/analysis_options.yaml` | espaço de trabalho Dart e regras de análise |
| `packages/corrida_core/lib/corrida_core.dart` | exporta tudo o que os apps usam |
| `.../src/money.dart`, `errors.dart`, `api_client.dart` | `brl`, `ApiException`/`NetworkException`, cliente HTTP |
| `.../src/session.dart`, `auth_api.dart` | sessão, armazenamento e login |
| `.../src/models/*.dart` | modelos do passageiro e do motoqueiro |
| `.../src/passenger_api.dart`, `rider_api.dart` | as rotas de cada papel |
| `.../src/realtime.dart` | WebSocket com reconexão e avisos |
| `packages/corrida_core/test/**` | testes com servidor de mentira |
| `packages/corrida_core/test_contract/**`, `mobile/tool/*` | teste de contrato contra o servidor real |
| `mobile/README.md` | como instalar, testar e rodar |

---

### Task 1: Dinheiro, erros e o cliente HTTP

**Files:**
- Create: `mobile/analysis_options.yaml`, `packages/corrida_core/lib/src/money.dart`, `errors.dart`, `api_client.dart`
- Modify: `packages/corrida_core/lib/corrida_core.dart`
- Test: `packages/corrida_core/test/money_test.dart`, `api_client_test.dart`

**Interfaces:**
- Produces: `String brl(int cents)` → `"R$ 7,50"`, `"R$ 1.234,00"`, `"-R$ 1,00"`;
  `class ApiException implements Exception { final int status; final String code; final String message; final String? field; final List<String> fields; }`;
  `class NetworkException implements Exception { final String message; }`;
  `class ApiClient { ApiClient({required Uri baseUrl, http.Client? httpClient, Duration timeout = const Duration(seconds: 15), void Function()? onUnauthorized}); String? token; Future<Object?> get(String path, {Map<String, String>? query}); Future<Object?> post(String path, {Object? body}); Future<Object?> put(String path, {Object? body}); Future<Object?> putBytes(String path, List<int> bytes, {required String contentType}); Uri get baseUrl; void close(); }` (devolve o JSON decodificado, `null` em 204).

- [ ] **Step 1: Testes que falham** — `money_test.dart`: `brl(0)`, `brl(5)` → `R$ 0,05`, `brl(750)`, `brl(123400)` → `R$ 1.234,00`, `brl(-100)`. `api_client_test.dart` (com `MockClient`): `get_devolve_o_json`, `post_204_devolve_null`, `manda_token_e_tipo_do_corpo` (cabeçalho `Authorization: Bearer abc` só com token; `content-type: application/json` em POST/PUT com corpo), `consulta_vai_codificada`, `erro_da_api_vira_api_exception` (`{"error":{"code":"quote_expired","message":"Esse preço não vale mais.","field":"x"}}` com 409), `erro_com_campos` (`fields`), `erro_que_nao_e_json_vira_api_exception_com_codigo_http` (HTML de proxy 502 → `http_502`), `corpo_de_sucesso_que_nao_e_json_vira_network_exception`, `401_com_token_avisa_uma_vez_e_limpa_o_token`, `401_sem_token_nao_avisa` (login com código errado), `falha_de_rede_vira_network_exception`, `tempo_esgotado_vira_network_exception`, `token_nao_aparece_na_mensagem_de_erro`, `put_bytes_manda_o_tipo_e_os_bytes`, `url_base_com_e_sem_barra_final`.
- [ ] **Step 2:** `dart test` em `packages/corrida_core`. Expected: falha (arquivos não existem).
- [ ] **Step 3: Implementar** (`http` com `Client` injetável; `timeout` em cada chamada; `utf8` explícito na decodificação).
- [ ] **Step 4:** `dart test` e `dart analyze`. Expected: passa, sem avisos.
- [ ] **Step 5: Commit** `feat(mobile): pacote corrida_core com dinheiro, erros e cliente HTTP`.

---

### Task 2: Sessão e entrada

**Files:**
- Create: `.../src/session.dart`, `.../src/auth_api.dart`
- Test: `.../test/session_test.dart`, `auth_api_test.dart`

**Interfaces:**
- Consumes: `ApiClient`, `ApiException`.
- Produces: `class Session { final String token, userId, role; final String? name; Map<String, Object?> toJson(); factory Session.fromJson(Map<String, Object?>) }`; `abstract class SessionStore { Future<Session?> load(); Future<void> save(Session s); Future<void> clear(); }` + `MemorySessionStore`;
  `class VerifyResult { final Session session; final bool isNewUser; }`;
  `class AuthApi { AuthApi(ApiClient client); Future<void> requestCode(String phone); Future<VerifyResult> verify({required String phone, required String code, required String role, String? device}); Future<void> logout(); Future<Me> me(); Future<Me> updateName(String name); }` (`Me`: `userId, phone, name, role`);
  `class SessionManager { SessionManager(AuthApi auth, SessionStore store, ApiClient client); Future<Session?> restore(); Future<VerifyResult> signIn({...mesmos de verify}); Future<void> signOut(); Session? get current; Stream<Session?> get changes; }` — `restore` põe o token no cliente; `signIn` guarda; `signOut` limpa o token e o armazenamento **mesmo se a rede falhar**; o `onUnauthorized` do cliente chama `signOut` local sem chamar a rede.

- [ ] **Step 1: Testes que falham:** `request_code_posta_o_telefone`; `verify_devolve_sessao_e_poe_o_token_no_cliente` (corpo enviado com `role` e `device`); `codigo_errado_levanta_code_invalid_e_nao_poe_token`; `me_e_update_name`; `session_vai_e_volta_em_json`; `restore_com_sessao_guardada_poe_o_token`; `restore_sem_nada_devolve_null`; `sign_in_guarda_e_avisa_em_changes`; `sign_out_limpa_mesmo_com_a_rede_fora`; `401_no_meio_do_uso_limpa_a_sessao_uma_vez_e_avisa`.
- [ ] **Step 2:** rodar. Expected: falha.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** `dart test`, `dart analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): sessão e entrada por código`.

---

### Task 3: Passageiro — modelos e rotas

**Files:**
- Create: `.../src/models/common.dart`, `passenger.dart`, `.../src/passenger_api.dart`
- Test: `.../test/passenger_models_test.dart`, `passenger_api_test.dart`

**Interfaces:**
- Produces: `class Place { final double lat, lng; final String text; toJson }`; `enum RideState { searching, queued, accepted, arrived, inProgress, completed, cancelled, noRider, unknown }` com `RideState.parse(String?)` (`"in_progress"` → `inProgress`; qualquer outro → `unknown`);
  `Quote`, `RiderCard`, `PixToPay`, `EndPayment`, `CancelInfo`, `QueueInfo`, `SafetyAlertRef`, `PassengerRide` (todos os campos da "Corrida (visão do passageiro)": `rideId, state, queued, priceCents, priceReason, method, pin, helmetConfirmed, pixPaid, payWithBalance, pickup, destination, distanceM, rider, riderPosition, queue, safetyAlert, pay, endPayment, cancel`), `PendingPayment`, `PendingFee`, `RecentFee`, `FeeAppeal`, `EmergencyContact`, `PassengerState` (todos os campos de `GET /v1/passenger/state`), `CancelResult` (`refund, feeCents, fee, refundTo, balanceCents`), `Charge`, `SosResult`; todos com `factory X.fromJson(Map<String, Object?>)`;
  `class PassengerApi { PassengerApi(ApiClient); Future<PassengerState> state(); Future<Quote> quote(Place pickup, Place destination); Future<PassengerRide> requestRide({required String quoteId, required String method}); Future<CancelResult> cancel(String rideId); Future<bool> payFee(); /* true se o saldo cobriu */ Future<Charge?> ...` — `payFee` devolve `PayFeeResult(paid, charge?)`; `appealFee(rideId, text)`; `topup(amountCents) → Charge`; `withdraw({amountCents, pixKey}) → Withdrawal`; `setEmergencyContact(name, phone)`; `rate(rideId, stars)`; `sos(rideId) → SosResult`; `safetyOk(rideId, alertId)`; `charge(chargeId) → Charge`.
  Os JSONs de exemplo dos testes são copiados de `docs/api-v1.md` e de uma resposta real do servidor (Tarefa 6 confere).

- [ ] **Step 1: Testes que falham:** um teste de modelo por tipo composto com JSON de exemplo completo e outro com os campos opcionais ausentes (`null`/padrão), `estado_desconhecido_da_corrida_nao_estoura`, `campo_novo_e_ignorado`, `dinheiro_vem_como_inteiro_mesmo_se_o_json_traz_double` (ex.: `700.0`); e para a API (com `MockClient`): rota, método e corpo exatos de cada chamada (`method: "balance"` na corrida, `pix_key` no saque, etc.) e a resposta virando o modelo; `erro_conhecido_chega_com_o_codigo` (`not_allowed`, `quote_expired`, `withdraw_disabled`).
- [ ] **Step 2:** rodar. Expected: falha.
- [ ] **Step 3: Implementar** (um leitor tolerante em `common.dart`: `asInt`, `asDouble`, `asString`, `asMap`, `asList`).
- [ ] **Step 4:** `dart test`, `dart analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): modelos e rotas do passageiro`.

---

### Task 4: Motoqueiro — modelos e rotas

**Files:**
- Create: `.../src/models/rider.dart`, `.../src/rider_api.dart`
- Test: `.../test/rider_models_test.dart`, `rider_api_test.dart`

**Interfaces:**
- Consumes: `Place`, `RideState`, `Charge`, `EndPayment` da Tarefa 3.
- Produces: `RiderState` (`registration`, `account`, `offer`, `ride`, `queuedRide`, `awaitingPayment`), `RiderRegistration` (`status` como `RegistrationStatus { notRegistered, pending, approved, rejected, blocked, unknown }`, `online, reason, rating, ratingCount, cnhExpiresOn, crlvExpiresOn`), `RiderAccount` (inclui `blockedReason`, `cashDebtCents`, `cashDebtLimitCents`, `debtToPayCents`, `needsEntry`), `Offer` (`rideId, priceCents, paymentMethod, pickup, destination, distanceM, secondsToPickup, willQueue, expiresAt`), `RiderRide`; 
  `class RiderApi { RiderApi(ApiClient); state(); goOnline(); goOffline(); sendPosition(lat, lng); accept(rideId) → RiderRide; decline(rideId); arrive(rideId); confirmHelmet(rideId); start(rideId, pin); complete(rideId); cashReceived(rideId); entryCharge() → Charge; debtCharge() → Charge; uploadDocument(kind, bytes, contentType) → UploadedDocument(key, bytes); register(RiderRegistrationForm) ; renewDocuments(...) }`; `goOnline` com 409 devolve `ApiException` com o `code` do motivo (`not_approved`, `blocked`, `documents_expired`, `entry_pending`, `debt_pending`).

- [ ] **Step 1: Testes que falham:** modelos (completo, parcial, desconhecido), uma chamada por rota (método, caminho, corpo), `start_manda_o_pin_e_wrong_pin_chega_com_o_codigo`, `upload_de_documento_manda_bytes_crus_com_o_tipo` e `foto_grande_demais_chega_como_413_file_too_large`, `register_manda_todos_os_campos_do_formulario`, `go_online_recusado_traz_o_motivo`.
- [ ] **Step 2:** rodar. Expected: falha.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** `dart test`, `dart analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): modelos e rotas do motoqueiro`.

---

### Task 5: Tempo real

**Files:**
- Create: `.../src/realtime.dart`
- Test: `.../test/realtime_test.dart`

**Interfaces:**
- Produces: `class ServerEvent { final String type; final Map<String, Object?> data; final double at; }`; `enum RealtimeStatus { connecting, ready, reconnecting, closed, unauthorized }`;
  `typedef WebSocketConnector = WebSocketChannel Function(Uri uri);`
  `class RealtimeClient { RealtimeClient({required Uri baseUrl, required String Function() tokenProvider, WebSocketConnector? connector, Duration pingEvery = const Duration(seconds: 25), List<Duration> backoff = const [1s, 2s, 4s, 8s, 15s], Future<void> Function(Duration)? delay /* para teste */ }); Stream<ServerEvent> get events; Stream<RealtimeStatus> get status; RealtimeStatus get currentStatus; Stream<void> get resync; void start(); Future<void> close(); }`.
  Comportamento: troca `http` por `ws` (e `https` por `wss`) em `/v1/ws`; a primeira mensagem enviada é `{"token": "..."}`; `ready` vira o status `ready` (e dispara `resync`, inclusive na reconexão); mensagens `{"type","data","at"}` viram `ServerEvent`; lixo que não é JSON é ignorado; manda `"ping"` a cada `pingEvery`; ao cair, tenta de novo com recuo crescente (zera depois de um `ready`); fechamento com código **4401** → status `unauthorized`, **não** reconecta; 4408 e qualquer outro → reconecta; `close()` encerra o canal, o relógio do ping e as tentativas, e nada mais é emitido depois.

- [ ] **Step 1: Testes que falham** (com um `WebSocketChannel` de mentira feito de `StreamChannelController`, e `delay` controlado): `manda_o_token_na_primeira_mensagem_e_nunca_na_url`; `ready_muda_o_status_e_pede_para_reler_o_estado`; `avisos_viram_server_event`; `mensagem_que_nao_e_json_e_ignorada`; `aviso_sem_data_vira_mapa_vazio`; `ping_periodico`; `cai_e_reconecta_com_recuo_crescente_e_zera_depois_do_ready`; `reconectar_pede_para_reler_o_estado_de_novo`; `4401_para_e_avisa_sem_reconectar`; `4408_reconecta`; `close_nao_emite_mais_nada_e_cancela_a_tentativa_pendente`; `token_novo_a_cada_tentativa` (usa `tokenProvider` de novo); `url_https_vira_wss`.
- [ ] **Step 2:** rodar. Expected: falha.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** `dart test`, `dart analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): cliente de tempo real com reconexão`.

---

### Task 6: Contrato com o servidor de verdade

**Files:**
- Create: `server/scripts/sandbox_server.py`, `packages/corrida_core/test_contract/contract_test.dart`, `mobile/tool/contrato.sh`
- Test: o próprio `contract_test.dart`

**Interfaces:**
- Produces: `server/scripts/sandbox_server.py` — sobe o servidor descartável do simulador (`simulator.sandbox.Sandbox(fast=True)`), escreve `URL=http://127.0.0.1:<porta>` e `ADMIN_PHONE=<telefone>` em um arquivo dado por `--out` e espera até receber `SIGTERM` (limpando o esquema). `mobile/tool/contrato.sh` — sobe o script, espera o arquivo, roda `dart test test_contract` com `CORRIDA_URL` e `CORRIDA_ADMIN_PHONE` no ambiente, derruba o servidor e devolve o código de saída. `contract_test.dart` só roda com `CORRIDA_URL` (senão `skip`).
- O teste faz: passageiro e motoqueiro entram pelo código (`/v1/dev/otp`); o administrador aprova o motoqueiro (rotas `/v1/admin/*` por `ApiClient` genérico); motoqueiro sobe documentos, cadastra-se, fica disponível, manda posição; passageiro cota, pede (dinheiro), o motoqueiro aceita, chega, confirma o capacete, inicia com o código, completa, confirma o dinheiro; os dois avaliam; os modelos do passageiro e do motoqueiro leem os estados reais em cada passo; o `RealtimeClient` de cada um recebe `rider_accepted`, `rider_arrived`, `trip_started`, `trip_completed` (passageiro) e `offer`, `ride_assigned` (motoqueiro); outra corrida paga com Pix (`/v1/dev/pix/{id}/pay`); outra corrida cancelada pelo passageiro mostra `CancelResult`. Erros esperados chegam com o `code` certo (`wrong_pin`, `quote_expired`).

- [ ] **Step 1: Escrever o teste de contrato** (e o script) — ainda sem rodar.
- [ ] **Step 2:** `mobile/tool/contrato.sh`. Expected: falha de verdade se algum modelo ou rota não bate com o servidor; corrigir o pacote (ou, se o servidor estiver certo e a doc errada, a doc) até passar.
- [ ] **Step 3:** repetir o script mais duas vezes. Expected: passa nas três (o servidor descartável nasce limpo a cada vez).
- [ ] **Step 4:** rodar `dart test` normal. Expected: o contrato aparece como "skipped".
- [ ] **Step 5: Commit** `test(mobile): contrato do cliente Dart contra o servidor de verdade`.

---

### Task 7: Documentos e fechamento

**Files:**
- Create: `mobile/README.md`
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`, `.gitignore` (se faltar `.dart_tool/`)
- Test: suíte do servidor não muda; `dart test`, `dart analyze` do pacote

- [ ] **Step 1:** README: como instalar o Flutter (`~/development/flutter`), o que ele faz com as licenças do Android, `dart pub get`, `dart test`, `tool/contrato.sh`, estrutura de pastas.
- [ ] **Step 2:** roteiro: linha 5A na tabela, seção "Itens que sobraram do plano 5A".
- [ ] **Step 3:** `dart test` e `dart analyze` no pacote, `mobile/tool/contrato.sh`. Expected: tudo passa.
- [ ] **Step 4: Commit** `docs: README dos apps e roteiro com o plano 5A`.
