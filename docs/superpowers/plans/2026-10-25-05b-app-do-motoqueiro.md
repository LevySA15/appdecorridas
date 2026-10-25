# App do motoqueiro (telas e navegação) — Plano de implementação (plano 5B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o aplicativo Flutter do motoqueiro (`mobile/apps/rider`): login, cadastro com fotos e espera da aprovação, ficar disponível, receber/aceitar/recusar ofertas (inclusive a que vai para a fila), levar o passageiro (cheguei → capacete → código → finalizar), cobrar o fim da corrida em dinheiro (QR do Pix ou "recebi"), pagar entrada e dívida, avaliar o passageiro e renovar documentos — usando o `corrida_core` (plano 5A), que já tem o cliente da API, a sessão e o tempo real.

**Architecture:** Igual ao app do passageiro (plano 6A): um `RiderController` (`ChangeNotifier`) é a única ponte entre as telas e o `corrida_core` (sessão, `RiderState`, tempo real, posição); as telas são widgets "burros" (dados + funções de retorno); toda a navegação mora em `app.dart`. Duas novidades: (1) as telas que os dois apps usam (login, mostrar Pix, avaliar, mapa de mentira) saem do app do passageiro para um pacote novo `corrida_ui`; (2) a posição do motoqueiro vem de um "mapa de mentira" (ele toca no mapa para se mover) e é enviada de 4 em 4 segundos, até a chave do Google e o GPS de verdade chegarem no plano 7.

**Tech Stack:** Flutter 3.47.7 / Dart 3.13, `corrida_core` (5A), `corrida_ui` (novo, local), `image_picker` (única dependência de terceiros nova, para as fotos do cadastro), `flutter_test`.

**Spec:** `docs/api-v1.md` (seções "Motoqueiro", "Cobrança", "Documentos", "Tempo real", "Códigos de erro"), `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (§ do app do motoqueiro, fila de uma corrida, regra "nada começa sozinho"), `docs/superpowers/plans/2026-10-23-06a-app-do-passageiro.md` (a estrutura que este plano repete). Sem spec de design própria — Levy aprovou direto na conversa ("pode ir").

## Decisões deste plano (minhas; o Levy disse "pode ir" e não escolheu uma a uma)

1. **Pacote `corrida_ui`** com as telas repetidas (login, mostrar Pix, avaliar) e o mapa de mentira, tirados do app do passageiro por `git mv`. Motivo: o polimento visual que o Levy deixou para depois fica em um lugar só. Custo se errado: um `git mv` de volta.
2. **Posição de mentira, sem GPS:** o motoqueiro se move tocando no mapa de mentira (e com atalhos "ir até o embarque/destino"), e o app envia a posição de 4 em 4 s enquanto está disponível ou numa corrida. GPS de verdade, serviço em primeiro plano e tela sempre acesa ficam para o plano 7 junto com o mapa do Google.
3. **Fotos do cadastro com `image_picker` (câmera)**, atrás de uma interface `PhotoSource` para os testes não precisarem do plugin. A selfie abre a câmera da frente.
4. **Sem "extrato do dia" ainda:** o servidor não tem rota para isso (`docs/api-v1.md` não lista uma). A tela inicial mostra o que o `state` já traz (corridas de teste, avaliação, dívida). O extrato vira item do roteiro (rota nova no servidor + tela).
5. **Aviso de oferta só com o app aberto:** vibração e som do sistema (`HapticFeedback`/`SystemSound`, que já vêm no Flutter). Notificação com o app fechado é Firebase (adiado desde o 5A).
6. **Oferta sem punição e sem automático:** aceitar e recusar são sempre toques do motoqueiro; o contador é só para mostrar (quem decide se a oferta venceu é o servidor, com `409 offer_gone`).
7. **Cadastro recusado não tem como reenviar:** o servidor só aceita um cadastro por número (`"Seu cadastro já foi enviado."`). A tela mostra o motivo e "fale com o suporte". Fica no roteiro como pergunta para o Levy.
8. **Sem SOS do motoqueiro:** a API só documenta o SOS no lado do passageiro.
9. **Visual simples** (Material padrão), como no 6A: função primeiro, polimento depois.

## Global Constraints

- **Dinheiro em centavos inteiros** (`int`); para mostrar, `brl(int)` de `corrida_core`.
- **Papel do login:** `role: "rider"` (literal; `server/app/api/routes/auth.py:23`).
- **Leitura tolerante** dos modelos já garantida por `corrida_core`; as telas só usam `RiderState`, `RiderRide`, `Offer`, `Charge` etc., nunca JSON cru.
- **Token nunca aparece na tela nem em mensagem de erro**; as telas mostram só `ApiException.message`/`NetworkException.message` (já em português) através de `friendlyMessage` (Tarefa 1).
- **Posição:** a cada 4 s (`docs/api-v1.md`, `POST /v1/rider/position`) enquanto `registration.online` **ou** há `state.ride`. Centro da cidade de mentira `lat: -12.9644, lng: -39.2597`, caixa de ±3000 m (igual ao 6A).
- **Nada começa sozinho** (spec, risco do Tema 1291 do STF): o app nunca aceita oferta, nunca começa corrida e nunca pune recusa; `offer.expires_at` (segundos, relógio do servidor) só alimenta um contador na tela.
- **Telas "burras":** recebem dados e funções por parâmetro; nenhuma chama `Navigator` nem importa `RiderApi`/`RealtimeClient`/`SessionManager`; só `RiderController` fala com o `corrida_core`, só `app.dart` navega.
- **Toda chamada que pode falhar** é pega dentro da tela, que mostra `friendlyMessage(e)` numa `SnackBar`; botão que dispara chamada fica desligado enquanto ela corre (toque duplo não repete a ação).
- **Sem pacote novo além de `image_picker`:** nada de mapa real, GPS, serviço em primeiro plano, Firebase, gerência de estado ou roteador.
- **Sem armazenamento seguro de token** neste plano (adiado no roteiro): `MemorySessionStore`.
- Comentários e textos para a pessoa em português do Brasil, simples; nomes de código em inglês.
- Comandos partem de `mobile/` com `export PATH="$HOME/development/flutter/bin:$PATH"`. Depois de mudar qualquer `pubspec.yaml`: `flutter pub get` em `mobile/`.
- Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Trabalho direto na `main` (convenção do projeto); um comando de git por vez.
- No `testWidgets`, tudo que liga o tempo real precisa de `await tester.runAsync(() => controller.signOut())` **dentro do corpo do teste** antes de terminar (o `close()` do `RealtimeClient` usa um `timeout` de verdade; `addTearDown` e `pump(Duration)` não resolvem) e o timer de posição precisa estar cancelado ao final (o `signOut` cancela).

## Review Focus

1. **A oferta some no instante em que o motoqueiro toca em "Aceitar"** (`409 offer_gone`, ou outra oferta toma o lugar): mensagem em português, a oferta velha desaparece, o app não abre a tela da corrida, e o contador de uma oferta nova recomeça (não herda o da anterior). Tarefas 5, 9, 11.
2. **O passageiro cancela (ou é bloqueado) com o motoqueiro dentro da tela da corrida** (`ride_cancelled`, `passenger_blocked`): a tela fecha sozinha, aparece o aviso (com a taxa de cancelamento quando houver) e nenhum botão de corrida morta sobra. Tarefa 11.
3. **A sessão vence (401) com o envio de posição rodando:** volta ao login na hora e a posição para de ser enviada (nem um `POST /v1/rider/position` depois). Tarefas 4, 7, 11.
4. **Cadastro: a segunda foto falha no envio (413, queda de rede):** as fotos escolhidas não se perdem e a que já subiu não sobe de novo no segundo toque (limite de 30 envios por hora); `duplicate_registration` mostra a mensagem do servidor sem apagar o formulário. Tarefas 6, 8.
5. **Começar a corrida:** código errado (`wrong_pin`, depois 429), Pix ainda não pago, capacete ainda não confirmado, toque duplo em "Finalizar": o botão certo fica desligado e nenhuma chamada sai duas vezes. Tarefa 10.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `mobile/pubspec.yaml` | acrescenta `packages/corrida_ui` e `apps/rider` ao espaço de trabalho |
| `mobile/packages/corrida_ui/**` | telas e mapa de mentira que os dois apps usam (login, mostrar Pix, avaliar, mapa, `friendlyMessage`) |
| `mobile/packages/corrida_core/lib/src/rider_api.dart` | ganha `charge(chargeId)` |
| `mobile/apps/rider/pubspec.yaml` | app Flutter (Android) |
| `.../lib/rider_controller.dart` | ponte única com `corrida_core`: sessão, estado, tempo real, ações, cadastro, posição |
| `.../lib/photo_source.dart` | `Photo`, `PhotoSource`, `ImagePickerPhotoSource`, `contentTypeOf` |
| `.../lib/registration_data.dart` | `RegistrationData` (o que o formulário de cadastro entrega) |
| `.../lib/dates.dart`, `lib/format.dart` | `parseBrDate`/`formatBrDate`; `km(int metros)` |
| `.../lib/screens/registration_screen.dart`, `status_screen.dart`, `renew_documents_screen.dart`, `document_photo_field.dart` | cadastro, espera/recusa/bloqueio, renovar documentos |
| `.../lib/screens/offer_card.dart`, `home_screen.dart` | oferta com contador; tela inicial do motoqueiro aprovado |
| `.../lib/screens/ride_screen.dart` | a corrida: buscar → cheguei → capacete e código → levar → finalizar |
| `.../lib/app.dart`, `lib/main.dart` | navegação, avisos do tempo real; montagem de verdade |
| `.../test/**` | testes de controlador e de tela |

---

### Task 1: Pacote `corrida_ui` (telas compartilhadas)

**Files:**
- Create: `mobile/packages/corrida_ui/pubspec.yaml`, `lib/corrida_ui.dart`, `lib/src/messages.dart`, `test/messages_test.dart`
- Move (`git mv`): `apps/passenger/lib/screens/{login_screen,charge_screen,rate_screen}.dart` e `apps/passenger/lib/fake_map.dart` → `packages/corrida_ui/lib/src/`; `apps/passenger/test/screens/{login_screen,charge_screen,rate_screen}_test.dart` e `apps/passenger/test/fake_map_test.dart` → `packages/corrida_ui/test/`
- Modify: `mobile/pubspec.yaml`, `apps/passenger/pubspec.yaml` (dependência de caminho `corrida_ui`), imports em `apps/passenger/lib/app.dart`, `lib/screens/request_ride_screen.dart` e nos testes do passageiro que importavam os arquivos movidos

**Interfaces:**
- Consumes: `corrida_core` (`ApiException`, `NetworkException`, `Place`, `Charge`, `brl`).
- Produces — `package:corrida_ui/corrida_ui.dart` exporta, com o mesmo comportamento de hoje: `LoginScreen`, `ChargeScreen`, `RateScreen`, `cityCenter`, `fakeMapHalfSizeM`, `pointFromTap`, `FakeMapPicker`; e novo:
```dart
/// A frase que a pessoa vê para um erro: a do servidor/rede, ou uma genérica.
String friendlyMessage(Object error);
```
  `ChargeScreen` passa a titular `'entry'` como "Pix da entrada" e `'debt'` como "Pix da dívida" (os outros títulos ficam).

- [ ] **Step 1: Criar o pacote e mover os arquivos.** `pubspec.yaml` do pacote: `name: corrida_ui`, `resolution: workspace`, `environment: sdk: ^3.13.0`, dependências `flutter` (sdk) e `corrida_core` (`path: ../corrida_core`), dev `flutter_test` (sdk). `lib/corrida_ui.dart` exporta os cinco arquivos de `lib/src/`. Acrescentar `packages/corrida_ui` ao `workspace:` de `mobile/pubspec.yaml`. `git mv` dos arquivos acima (nada de copiar) e ajustar os imports de dentro deles (`package:passenger/...` → relativos ou `package:corrida_ui/corrida_ui.dart`). `flutter pub get`.
- [ ] **Step 2: Escrever os testes que falham.** `test/messages_test.dart`: `ApiException` → devolve o `message`; `NetworkException` → o `message`; qualquer outra coisa → `'Algo deu errado. Tente de novo.'`. Em `charge_screen_test.dart` (já movido): `Charge(purpose: 'entry', ...)` mostra o título `'Pix da entrada'` e `purpose: 'debt'` mostra `'Pix da dívida'`.
- [ ] **Step 3:** `cd packages/corrida_ui && flutter test`. Expected: falha — `friendlyMessage` não existe e os dois títulos novos não batem.
- [ ] **Step 4: Implementar** `friendlyMessage` em `lib/src/messages.dart`, usá-lo no lugar dos três `_messageOf` das telas movidas, e acrescentar os dois títulos. Em `apps/passenger` trocar os imports (`app.dart`, `request_ride_screen.dart`, testes) por `package:corrida_ui/corrida_ui.dart` e acrescentar `corrida_ui: path: ../../packages/corrida_ui` às dependências. (As outras cópias de `_messageOf` do passageiro ficam como estão — item adiado.)
- [ ] **Step 5:** `flutter test` em `packages/corrida_ui` e em `apps/passenger`, e `flutter analyze` em `mobile/`. Expected: tudo passa (o passageiro continua com os mesmos testes de antes, só que parte deles mora no `corrida_ui`), sem avisos.
- [ ] **Step 6: Commit** `refactor(mobile): telas compartilhadas dos apps no pacote corrida_ui`.

---

### Task 2: Passageiro — avaliar fecha a tela de avaliar

Achado ao ler o 6A para este plano: depois de avaliar com sucesso, `RateScreen` continua na tela (só "Agora não" fecha), e um segundo toque dá `409 already_rated`.

**Files:**
- Modify: `mobile/apps/passenger/lib/app.dart` (`_onEvent`, o `onRate` da `RateScreen`)
- Test: `mobile/apps/passenger/test/app_test.dart`

**Interfaces:** nenhuma nova.

- [ ] **Step 1: Teste que falha** (`app_test.dart`, no mesmo molde de `'trip_completed abre a tela de avaliar com o ride_id certo'`): `'avaliar com sucesso fecha a tela de avaliar'` — depois do toque na estrela e do `pumpAndSettle`, `find.byType(RateScreen)` é `findsNothing` e `find.byType(HomeScreen)` é `findsOneWidget`; termina com `await tester.runAsync(() => m.controller.signOut())`.
- [ ] **Step 2:** `cd apps/passenger && flutter test test/app_test.dart`. Expected: falha no novo teste (a tela de avaliar continua).
- [ ] **Step 3: Implementar:** o `onRate` passa a ser `(stars) async { await widget.controller.rate(rideId: rideId, stars: stars); final nav = _navigatorKey.currentState; if (nav != null && nav.canPop()) nav.pop(); }`. Erro de `rate` continua subindo para a tela, que mostra a mensagem e fica.
- [ ] **Step 4:** `flutter test` (todo o app do passageiro) e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `fix(mobile): avaliar a corrida fecha a tela de avaliar`.

---

### Task 3: Mapa de mentira só para ver (`FakeMapView`)

**Files:**
- Modify: `mobile/packages/corrida_ui/lib/src/fake_map.dart`
- Test: `mobile/packages/corrida_ui/test/fake_map_test.dart`

**Interfaces:**
- Consumes: `Place`, `cityCenter`, `pointFromTap` (já no arquivo).
- Produces (exportados por `corrida_ui.dart`):
```dart
Offset offsetFromPlace(Place place, Size size);   // o inverso de pointFromTap (hoje _offsetFromPoint, privado)

enum MarkerKind { me, pickup, destination }       // azul, verde, vermelho

class MapMarker {
  const MapMarker(this.kind, this.place);
  final MarkerKind kind;
  final Place place;
}

/// Mapa de mentira sem escolha de origem/destino: desenha os marcadores e, se `onTap` existir, devolve o
/// ponto tocado (é assim que o motoqueiro "anda").
class FakeMapView extends StatelessWidget {
  const FakeMapView({required this.markers, this.onTap, super.key});
  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;
}
```
`FakeMapPicker` passa a usar `offsetFromPlace` público.

- [ ] **Step 1: Testes que falham** (`fake_map_test.dart`): `'offsetFromPlace e o inverso de pointFromTap'` — para `Offset(0,0)`, `(300,300)`, `(75,210)` num `Size(300,300)`, `offsetFromPlace(pointFromTap(o, size), size)` fica a menos de `1e-6` de `o` nos dois eixos; `'toque no mapa de ver entrega o ponto'` (`testWidgets`) — `FakeMapView` com um marcador `me` em `cityCenter`, dentro de `SizedBox(width: 300, height: 300)`, `tester.tapAt` no centro chama `onTap` com um `Place` a menos de `1e-6` de `cityCenter`; `'sem onTap o toque nao faz nada'` — o mesmo sem `onTap` não lança erro.
- [ ] **Step 2:** `cd packages/corrida_ui && flutter test test/fake_map_test.dart`. Expected: falha — nomes não existem.
- [ ] **Step 3: Implementar** (um `CustomPainter` com as cores acima; `GestureDetector.onTapDown` só quando `onTap != null`).
- [ ] **Step 4:** `flutter test` em `packages/corrida_ui` e em `apps/passenger`, `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): mapa de mentira só para ver, com marcadores`.

---

### Task 4: Esqueleto do app do motoqueiro e `RiderController` (sessão, estado, tempo real)

**Files:**
- Create: `mobile/apps/rider/pubspec.yaml`, `lib/rider_controller.dart`, `lib/main.dart` (provisório: `runApp(const MaterialApp(home: SizedBox()))`, trocado na Tarefa 11), `test/support/fakes.dart` (`FakeSink`, `FakeChannel` com `servidorMandaAviso(type, data)`, `json(body, [status])` — copiados de `apps/passenger/test/app_test.dart`), `test/rider_controller_test.dart`
- Modify: `mobile/pubspec.yaml` (acrescenta `apps/rider`)

**Interfaces:**
- Consumes (`corrida_core`): `AuthApi`, `SessionManager`, `MemorySessionStore`, `RiderApi`, `RealtimeClient`, `WebSocketConnector`, `ServerEvent`, `Session`, `RiderState`.
- Produces:
```dart
class RiderController extends ChangeNotifier {
  RiderController({
    required AuthApi authApi,
    required SessionManager session,   // o parâmetro chama-se `session`; o campo é `sessionManager` (igual ao PassengerController)
    required RiderApi api,
    required Uri realtimeBaseUrl,
    WebSocketConnector? realtimeConnector,
  });

  bool get starting;                 // true até o restore() inicial terminar
  Session? get session;
  RiderState? get state;
  Stream<ServerEvent> get events;    // avisos crus, republicados

  Future<void> start();              // restore(); com sessão: liga o tempo real e lê o state
  Future<void> requestCode(String phone);
  Future<void> verify({required String phone, required String code});   // role: 'rider'
  Future<void> signOut();
  Future<void> refreshState();       // GET /v1/rider/state; atualiza `state` e avisa
  void dispose();
}
```
Mesma mecânica do `PassengerController` (`apps/passenger/lib/passenger_controller.dart`): qualquer aviso ou `resync` do tempo real dispara um `refreshState()` silencioso (erro de rede é ignorado); `signOut()` fecha o tempo real antes de sair e limpa o `state`; um `null` em `sessionManager.changes` (401) fecha o tempo real e limpa o `state`.

- [ ] **Step 1: Criar o app e ligar ao espaço de trabalho.**
```bash
cd mobile
flutter create --platforms=android --org com.reconcavo --project-name rider -t app apps/rider
rm apps/rider/analysis_options.yaml apps/rider/*.iml apps/rider/pubspec.lock apps/rider/test/widget_test.dart
```
`apps/rider/pubspec.yaml`: `name: rider`, `description: App do motoqueiro.`, `publish_to: none`, `resolution: workspace`, `version: 1.0.0+1`, `environment: sdk: ^3.13.0`; dependências `flutter` (sdk), `corrida_core` (`path: ../../packages/corrida_core`), `corrida_ui` (`path: ../../packages/corrida_ui`); dev `flutter_test` (sdk), `http: ^1.2.0`, `stream_channel: ^2.1.0`, `web_socket_channel: ^3.0.0`; `flutter: uses-material-design: true`. Acrescentar `- apps/rider` ao `workspace:` de `mobile/pubspec.yaml`; `flutter pub get`.
- [ ] **Step 2: Testes que falham** (`rider_controller_test.dart`, `test()` comum, `ApiClient(baseUrl: Uri.parse('http://s.teste'), httpClient: MockClient(handler))` e `realtimeConnector` de mentira de `support/fakes.dart`; o estado mínimo válido é `{"registration":{"status":"not_registered"},"account":null,"offer":null,"ride":null,"queued_ride":null,"awaiting_payment":null}`):
  - `comeca sem sessao guardada fica esperando login` — `session` e `state` nulos, `starting` falso, o conector de tempo real não foi chamado.
  - `comeca com sessao guardada carrega o estado e liga o tempo real`.
  - `verify entra pelo papel rider` — o corpo do `POST /v1/auth/verify` tem `"role":"rider"`; depois dele `session` e `state` existem e o tempo real está ligado.
  - `sign out desliga o tempo real e limpa tudo` — o canal de mentira foi fechado.
  - `aviso de tempo real atualiza o estado` — a resposta do `GET /v1/rider/state` muda, um aviso qualquer chega, `state` reflete a nova resposta.
  - `quem assina events recebe os avisos crus` — `ServerEvent.type == 'algum_aviso'`.
  - `401 fecha o tempo real e limpa sessao e estado`.
- [ ] **Step 3:** `cd apps/rider && flutter test test/rider_controller_test.dart`. Expected: falha — `RiderController` não existe.
- [ ] **Step 4: Implementar** como descrito.
- [ ] **Step 5:** `flutter test test/rider_controller_test.dart` e `flutter analyze`. Expected: passa, sem avisos.
- [ ] **Step 6: Commit** `feat(mobile): esqueleto do app do motoqueiro e o controlador`.

---

### Task 5: Ações do motoqueiro no controlador (+ `RiderApi.charge`)

**Files:**
- Modify: `mobile/packages/corrida_core/lib/src/rider_api.dart`, `mobile/apps/rider/lib/rider_controller.dart`
- Test: `mobile/packages/corrida_core/test/rider_api_test.dart`, `mobile/apps/rider/test/rider_actions_test.dart`

**Interfaces:**
- Consumes: `RiderApi` (`goOnline, goOffline, accept, decline, arrive, confirmHelmet, start, complete, cashReceived, rate, entryCharge, debtCharge`), `RiderRide`, `Charge`, `ApiException`.
- Produces:
```dart
// corrida_core
Future<Charge> RiderApi.charge(String chargeId);   // GET /v1/charges/{id} (a mesma rota do passageiro)

// RiderController — cada ação chama a API e depois refreshState()
Future<void> goOnline();
Future<void> goOffline();
Future<RiderRide> accept(String rideId);
Future<void> decline(String rideId);
Future<void> arrive(String rideId);
Future<void> confirmHelmet(String rideId);
Future<void> startTrip(String rideId, String pin);
Future<void> completeTrip(String rideId);
Future<void> cashReceived(String rideId);
Future<void> rate({required String rideId, required int stars});   // sem refreshState: a corrida já saiu do state
Future<Charge> entryCharge();
Future<Charge> debtCharge();
Future<Charge> loadCharge(String chargeId);
```
Regra: se a chamada falhar com `ApiException`, o controlador faz uma releitura silenciosa do `state` **antes** de repassar o erro (o `409 offer_gone` ou `invalid_state` quase sempre quer dizer que o estado mudou por baixo; a tela não pode ficar com a oferta velha).

- [ ] **Step 1: Testes que falham.** `rider_api_test.dart`: `charge` faz `GET /v1/charges/c9` e devolve `Charge` com `chargeId`/`brCode` lidos. `rider_actions_test.dart` (`MockClient` que guarda os pedidos em uma lista; depois de cada ação, uma segunda leitura do `GET /v1/rider/state` é contada): uma tabela verificando método, caminho e corpo — `goOnline` → `POST /v1/rider/online`; `goOffline` → `/offline`; `accept('r1')` → `POST /v1/rider/offers/r1/accept` e devolve a `RiderRide`; `decline('r1')` → `/offers/r1/decline`; `arrive`/`confirmHelmet`/`completeTrip` → `/rides/r1/arrive`, `/helmet`, `/complete`; `startTrip('r1','1234')` → `/rides/r1/start` com corpo `{"pin":"1234"}`; `cashReceived` → `/rides/r1/cash-received`; `rate(rideId:'r1', stars:5)` → `POST /v1/rides/r1/rating` com `{"stars":5}` e **sem** nova leitura do state; `entryCharge`/`debtCharge` → `POST /v1/rider/entry-charge`/`debt-charge`. E:
  - `accept com 409 offer_gone le o estado de novo e repassa o erro` — o `accept` responde 409 `offer_gone`, o `state` seguinte vem sem oferta; depois do `expect(..., throwsA(isA<ApiException>().having((e) => e.code, 'code', 'offer_gone')))`, `controller.state!.offer` é `null`.
  - `wrong_pin 422 repassa o erro e mantem a corrida no estado`.
- [ ] **Step 2:** `dart test test/rider_api_test.dart` em `packages/corrida_core` e `flutter test test/rider_actions_test.dart` em `apps/rider`. Expected: falham.
- [ ] **Step 3: Implementar** (um auxiliar privado `_act<T>(Future<T> Function())` no controlador: sucesso → `refreshState()`; `ApiException` → `_quietRefresh()` e `rethrow`).
- [ ] **Step 4:** os testes acima, `dart test && dart analyze` em `packages/corrida_core`, `flutter test` em `apps/rider` e `flutter analyze` em `mobile/`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): ações do motoqueiro no controlador e RiderApi.charge`.

---

### Task 6: Cadastro e documentos no controlador (fotos)

**Files:**
- Create: `mobile/apps/rider/lib/photo_source.dart`, `lib/registration_data.dart`
- Modify: `mobile/apps/rider/pubspec.yaml` (`flutter pub add image_picker` em `apps/rider`), `lib/rider_controller.dart`
- Test: `mobile/apps/rider/test/photo_source_test.dart`, `test/rider_registration_test.dart`

**Interfaces:**
- Consumes: `RiderApi.uploadDocument`, `register`, `renewDocuments`, `DocKind`, `RiderRegistrationForm`, `image_picker` (`ImagePicker`, `ImageSource.camera`, `CameraDevice`).
- Produces:
```dart
class Photo { const Photo({required this.bytes, required this.contentType}); final List<int> bytes; final String contentType; }

abstract class PhotoSource { Future<Photo?> pick(DocKind kind); }          // null = a pessoa desistiu

class ImagePickerPhotoSource implements PhotoSource {
  // câmera; selfie com a câmera da frente; maxWidth 1600 e imageQuality 85 (fica longe dos 8 MB do servidor)
}

String contentTypeOf(String path);   // .jpg/.jpeg → image/jpeg, .png → image/png, .webp → image/webp (sem diferenciar maiúsculas); outro → image/jpeg

class RegistrationData {
  const RegistrationData({required this.name, required this.cpf, required this.cnhNumber, required this.plate,
      required this.motoModel, required this.cnhExpiresOn, required this.crlvExpiresOn, required this.photos});
  final String name, cpf, cnhNumber, plate, motoModel;
  final DateTime cnhExpiresOn, crlvExpiresOn;
  final Map<DocKind, Photo> photos;   // precisa ter as três
}

// RiderController (o construtor ganha `PhotoSource? photos`; padrão: ImagePickerPhotoSource())
Future<Photo?> pickPhoto(DocKind kind);
Future<void> registerRider(RegistrationData data);                        // envia as 3 fotos, cadastra, refreshState()
Future<void> renewDocuments({required DateTime cnhExpiresOn, required DateTime crlvExpiresOn, Photo? cnhPhoto, Photo? crlvPhoto});
```
`registerRider` envia na ordem selfie, cnh, crlv (um `PUT /v1/rider/documents/{kind}` com a foto crua) e só depois faz `POST /v1/rider/register` com as chaves devolvidas. O controlador lembra a chave de cada foto já enviada **por identidade do objeto `Photo`** (`identical`); no segundo toque depois de uma falha, o que já subiu não sobe de novo. O cache some quando o cadastro dá certo. `renewDocuments` envia só as fotos dadas (`cnh_photo_key`/`crlv_key` só entram no corpo quando há foto) e relê o state.

- [ ] **Step 1: Testes que falham.** `photo_source_test.dart`: `contentTypeOf` para `a.jpg`, `A.JPEG`, `x.png`, `y.webp`, `sem_extensao` e `foto.heic` (→ `image/jpeg`). `rider_registration_test.dart` (`PhotoSource` falso; `MockClient` contando os `PUT`):
  - `cadastro envia as tres fotos em ordem e depois cadastra` — ordem `selfie, cnh, crlv` e então `POST /v1/rider/register` cujo corpo traz `selfie_key`, `cnh_photo_key`, `crlv_key` iguais às devolvidas, `cnh_expires_on` em `AAAA-MM-DD` e o resto dos campos; depois disso o state é relido.
  - `foto que ja subiu nao sobe de novo no segundo toque` — o `PUT` da `cnh` responde 413 `file_too_large` na primeira vez: o primeiro `registerRider` lança `ApiException` (code `file_too_large`) com 1 `PUT` de selfie e 2 de cnh feitos; o segundo, com os **mesmos** objetos `Photo` e o servidor agora respondendo 201, termina com apenas 1 `PUT` de selfie no total, 2 de cnh no total e 1 de crlv.
  - `cadastro duplicado repassa a mensagem do servidor` — `POST /register` responde 409 `duplicate_registration`; a `ApiException` sobe com a mensagem; o cache de fotos continua (um terceiro toque não envia fotos de novo).
  - `renovar documentos envia so a foto dada` — com `cnhPhoto` e sem `crlvPhoto`: 1 `PUT` (`cnh`), e o corpo de `POST /v1/rider/documents/renew` tem `cnh_photo_key` e não tem `crlv_key`.
- [ ] **Step 2:** `cd apps/rider && flutter pub add image_picker && flutter test test/photo_source_test.dart test/rider_registration_test.dart`. Expected: falham — arquivos e métodos não existem.
- [ ] **Step 3: Implementar.** `ImagePickerPhotoSource.pick` lê os bytes com `XFile.readAsBytes()` e o tipo com `contentTypeOf(file.path)`.
- [ ] **Step 4:** os testes acima, `flutter test` (todo o app) e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): cadastro e documentos do motoqueiro com fotos`.

---

### Task 7: Posição de mentira enviada de 4 em 4 segundos

**Files:**
- Modify: `mobile/apps/rider/lib/rider_controller.dart`, `mobile/apps/rider/pubspec.yaml` (dev: `fake_async: ^1.3.0`, já resolvido pelo `flutter_test`)
- Test: `mobile/apps/rider/test/rider_position_test.dart`

**Interfaces:**
- Consumes: `RiderApi.sendPosition`, `cityCenter` (`corrida_ui`), `Place`.
- Produces (o construtor ganha `Duration positionEvery = const Duration(seconds: 4)`):
```dart
Place get position;          // começa em cityCenter
void moveTo(Place place);    // muda a posição e avisa os ouvintes; o envio vai no próximo ciclo
```
Regra: depois de cada `refreshState()`, o controlador confere se deve enviar: `session != null && state != null && (state.registration.online || state.ride != null)`. Se deve e não há ciclo, envia uma vez na hora e começa o `Timer.periodic(positionEvery)`; se não deve, cancela o ciclo. Sair, 401 e `dispose` cancelam. Erro de envio (`ApiException`/`NetworkException`) é ignorado — o 401 já é tratado pelo `ApiClient` — e não para o ciclo.

- [ ] **Step 1: Testes que falham** (`fakeAsync` de `package:fake_async`, `MockClient` contando os `POST /v1/rider/position`; o estado do teste muda entre as leituras):
  - `parado e sem corrida nao envia` — `online:false`, `ride:null`: depois de `start()` e 12 s, nenhum envio.
  - `disponivel envia na hora e de 4 em 4 segundos` — `online:true`: 1 envio logo depois de `start()` e 3 depois de 8 s, com `{"lat": -12.9644, "lng": -39.2597}`.
  - `moveTo muda o que vai no proximo envio`.
  - `em corrida envia mesmo com online false`.
  - `ficar offline para de enviar` — depois de `goOffline()` (state: `online:false`, sem corrida) mais 8 s não geram envio novo.
  - `sessao vencida para de enviar` — o state seguinte responde 401; depois disso, 8 s sem envio.
  - `erro de rede no envio nao derruba nem para o ciclo` — o primeiro envio lança `NetworkException`; o seguinte acontece.
- [ ] **Step 2:** `flutter test test/rider_position_test.dart`. Expected: falha — `position`/`moveTo` não existem.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** o teste acima, `flutter test`, `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): posição de mentira do motoqueiro enviada a cada 4 segundos`.

---

### Task 8: Telas de cadastro, espera e renovação de documentos

**Files:**
- Create: `mobile/apps/rider/lib/dates.dart`, `lib/screens/document_photo_field.dart`, `lib/screens/registration_screen.dart`, `lib/screens/status_screen.dart`, `lib/screens/renew_documents_screen.dart`
- Test: `test/dates_test.dart`, `test/screens/registration_screen_test.dart`, `test/screens/status_screen_test.dart`, `test/screens/renew_documents_screen_test.dart`

**Interfaces:**
- Consumes: `Photo`, `RegistrationData`, `RiderRegistration`, `RegistrationStatus`, `DocKind`, `friendlyMessage`.
- Produces:
```dart
DateTime? parseBrDate(String text);   // "dd/mm/aaaa"; null se vazio, 31/02, mês 13 ou ano < 1900
String formatBrDate(DateTime date);   // "dd/mm/aaaa"

class DocumentPhotoField extends StatelessWidget {
  const DocumentPhotoField({required this.label, required this.photo, required this.onPick, super.key});
  final String label; final Photo? photo; final VoidCallback onPick;   // "Tirar foto" / "Foto tirada — trocar"
}

class RegistrationScreen extends StatefulWidget {
  const RegistrationScreen({required this.onPickPhoto, required this.onSubmit, required this.onSignOut, super.key});
  final Future<Photo?> Function(DocKind kind) onPickPhoto;
  final Future<void> Function(RegistrationData data) onSubmit;
  final VoidCallback onSignOut;
}

class StatusScreen extends StatelessWidget {
  const StatusScreen({required this.registration, required this.onRefresh, required this.onSignOut, super.key});
  final RiderRegistration registration;
  final Future<void> Function() onRefresh;
  final VoidCallback onSignOut;
}

class RenewDocumentsScreen extends StatefulWidget {
  const RenewDocumentsScreen({required this.onPickPhoto, required this.onSubmit, super.key});
  final Future<Photo?> Function(DocKind kind) onPickPhoto;
  final Future<void> Function(DateTime cnhExpiresOn, DateTime crlvExpiresOn, Photo? cnhPhoto, Photo? crlvPhoto) onSubmit;
}
```
Textos de `StatusScreen`: `pending` → "Cadastro em análise. Avisamos aqui quando for aprovado."; `rejected` → "Cadastro recusado" + o `reason` (se houver) + "Fale com o suporte."; `blocked` → "Conta bloqueada" + o `reason`; qualquer outro → "Não conseguimos ler o seu cadastro. Toque em atualizar."; botões "Atualizar" (erro vira `SnackBar`) e "Sair".
`RegistrationScreen`: campos Nome, CPF, Número da CNH, Placa, Modelo da moto, Validade da CNH, Validade do documento da moto (as duas datas em `dd/mm/aaaa`), e três `DocumentPhotoField` (Selfie, CNH, Documento da moto). Ao enviar: texto vazio → "Preencha este campo"; data que `parseBrDate` não lê → "Use dd/mm/aaaa"; foto faltando → "Falta a foto" (nada disso chama `onSubmit`). Erro de `onSubmit` vai para uma `SnackBar` e **mantém** campos e fotos. Botão desligado enquanto envia.

- [ ] **Step 1: Testes que falham.** `dates_test`: `parseBrDate('05/11/2030')` → 2030-11-05; `'31/02/2030'` → `null`; `'5/11/2030'` → `null` (exige `dd/mm/aaaa` com zeros); `''` → `null`; `'05/13/2030'` → `null`; `formatBrDate` de `DateTime(2030, 1, 9)` → `'09/01/2030'`. `registration_screen_test`: `'campos vazios mostram os avisos e nao enviam'`; `'data invalida mostra Use dd/mm/aaaa'`; `'sem foto mostra Falta a foto'`; `'tudo preenchido envia os dados certos'` (o `onPickPhoto` de teste devolve uma `Photo` fixa por tipo; o `RegistrationData` recebido tem os textos digitados, as datas lidas e as três fotos); `'erro do servidor mostra a mensagem e mantem o formulario'` (`ApiException` 409 `duplicate_registration` "Esse CPF já tem cadastro."; os campos digitados e o texto "Foto tirada" continuam); `'foto cancelada continua pedindo a foto'` (`onPickPhoto` devolve `null`). `status_screen_test`: um teste por status (`pending`, `rejected` com motivo, `blocked` com motivo, `unknown`) e `'atualizar chama onRefresh'` e `'erro ao atualizar mostra a mensagem'`. `renew_documents_screen_test`: datas inválidas não enviam; datas boas sem foto chamam `onSubmit` com `null, null`; com a foto da CNH tirada chamam com ela.
- [ ] **Step 2:** `flutter test test/dates_test.dart test/screens`. Expected: falham — nada existe.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** os testes acima e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): telas de cadastro, espera e renovação de documentos do motoqueiro`.

---

### Task 9: `OfferCard` e `HomeScreen` do motoqueiro

**Files:**
- Create: `mobile/apps/rider/lib/format.dart`, `lib/screens/offer_card.dart`, `lib/screens/home_screen.dart`
- Test: `test/format_test.dart`, `test/screens/offer_card_test.dart`, `test/screens/home_screen_test.dart`

**Interfaces:**
- Consumes: `RiderState`, `Offer`, `RiderRide`, `Charge`, `brl`, `formatBrDate`, `friendlyMessage`.
- Produces:
```dart
String km(int meters);   // < 1000 → "350 m"; senão "1,2 km" (uma casa, vírgula)

class OfferCard extends StatefulWidget {
  const OfferCard({required this.offer, required this.onAccept, required this.onDecline, this.clock, super.key});
  final Offer offer;
  final Future<void> Function() onAccept;
  final Future<void> Function() onDecline;
  final DateTime Function()? clock;   // só para teste
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.state, required this.onGoOnline, required this.onGoOffline,
    required this.onAcceptOffer, required this.onDeclineOffer, required this.onOpenRide,
    required this.onPayEntry, required this.onPayDebt, required this.onLoadCharge, required this.onShowCharge,
    required this.onCashReceived, required this.onRenewDocuments, required this.onSignOut,
    this.clock, super.key,
  });
  final RiderState state;
  final Future<void> Function() onGoOnline, onGoOffline;
  final Future<void> Function(String rideId) onAcceptOffer, onDeclineOffer, onCashReceived;
  final VoidCallback onOpenRide, onRenewDocuments, onSignOut;
  final Future<Charge> Function() onPayEntry, onPayDebt;
  final Future<Charge> Function(String chargeId) onLoadCharge;
  final void Function(Charge) onShowCharge;
  final DateTime Function()? clock;
}
```
`OfferCard` mostra o valor (`brl`), a forma de pagamento ("Dinheiro" para `cash`, senão "Pix"), a distância da corrida (`km`), "N min até o passageiro" quando `secondsToPickup != null` (arredondado para cima), os textos de embarque/destino quando não vazios, "Esta corrida espera na fila: você termina a de agora primeiro." quando `willQueue`, e o contador "Responda em Ns" (`max(0, ceil(expiresAt − agora em segundos))`, atualizado a cada 1 s por `Timer.periodic` cancelado no `dispose`; com 0 mostra "Tempo esgotado"). Os botões "Aceitar" e "Recusar" **continuam ligados** com o contador em zero (decide o servidor); enquanto uma chamada corre os dois ficam desligados; erro → `SnackBar`. Se o `rideId` da oferta muda (`didUpdateWidget`), o estado de "ocupado" e o contador recomeçam.
`HomeScreen`, de cima para baixo: (1) `SwitchListTile` "Estou rodando" ligado a `registration.online` (ligar chama `onGoOnline`, desligar `onGoOffline`; erro → `SnackBar` com a frase do servidor); (2) faixa de bloqueio: `blockedReason == 'entry_pending'` → "Você fez as {trialRides} corridas de teste. Pague a entrada de {brl} para continuar." + "Pagar entrada" (`onPayEntry` → `onShowCharge`); `'debt_pending'` → "Taxa a pagar: {brl(debtToPayCents)}" + "Pagar taxa" (`onPayDebt` → `onShowCharge`); (3) aviso de documento: CNH ou documento da moto vencido ("{Documento} venceu em {data}") ou vencendo em até 30 dias ("vence em {data}") + "Enviar novo" (`onRenewDocuments`); (4) `OfferCard` se `state.offer != null`; (5) se `state.ride != null`, cartão "Corrida em andamento" com "Abrir corrida" (`onOpenRide`); (6) se `state.queuedRide != null`, "Próxima na fila: {passengerName}" (só texto); (7) se `state.awaitingPayment != null`, cartão "Cobrar {brl(endPayment?.amountCents ?? priceCents)} em dinheiro" com "Ver Pix" (**só** se `endPayment?.chargeId != null`: `onLoadCharge` → `onShowCharge`) e "Recebi o dinheiro" (`onCashReceived(rideId)`), e a frase "O passageiro foi bloqueado até pagar; você recebe quando ele pagar." quando `endPayment?.blocked == true`; (8) resumo: "Corridas de teste: {completedRides} de {trialRides}" enquanto `!entryPaid`, avaliação "{rating} ({ratingCount} avaliações)" quando houver, "Taxas devidas: {brl}" quando `cashDebtCents > 0`; (9) "Sair".

- [ ] **Step 1: Testes que falham.** `format_test`: `km(350)` → `"350 m"`, `km(1000)` → `"1,0 km"`, `km(1250)` → `"1,3 km"`. `offer_card_test` (com `clock` fixo): mostra valor, "Dinheiro"/"Pix", distância, "3 min até o passageiro" (para 130 s), a frase da fila só com `willQueue`; contador "Responda em 10s" com `expiresAt = agora + 10` e, depois de `tester.pump(const Duration(seconds: 1))` com o relógio avançado, "Responda em 9s"; "Tempo esgotado" com 0 e **os dois botões ainda tocáveis**; "Aceitar" chama `onAccept` uma vez mesmo com dois toques seguidos (segundo toque cai com o botão desligado); `onAccept` lançando `ApiException` (409 "Essa oferta não está mais disponível.") mostra a frase e religa os botões; trocar a `Offer` por outra de `rideId` diferente reinicia o contador. `home_screen_test`: o `Switch` chama `onGoOnline` quando desligado e `onGoOffline` quando ligado; erro do `onGoOnline` mostra a frase; faixa `entry_pending` e toque em "Pagar entrada" chama `onShowCharge` com a cobrança; faixa `debt_pending` idem; aviso de documento vence em 10 dias (com `clock`) / venceu / não aparece com 90 dias; `OfferCard` aparece com oferta e "Aceitar" chama `onAcceptOffer('r1')`; "Abrir corrida" com `ride`; texto da fila; cartão de cobrança: "Ver Pix" some sem `chargeId`, "Recebi o dinheiro" chama `onCashReceived('r1')`, a frase de bloqueado aparece com `blocked: true`; resumo de teste/avaliação/taxa.
- [ ] **Step 2:** `flutter test test/format_test.dart test/screens/offer_card_test.dart test/screens/home_screen_test.dart`. Expected: falham.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** os testes acima e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): oferta com contador e tela inicial do motoqueiro`.

---

### Task 10: `RideScreen` do motoqueiro

**Files:**
- Create: `mobile/apps/rider/lib/screens/ride_screen.dart`
- Test: `test/screens/ride_screen_test.dart`

**Interfaces:**
- Consumes: `RiderRide`, `RideState`, `Offer`, `Place`, `FakeMapView`, `MapMarker`, `MarkerKind`, `OfferCard`, `brl`, `friendlyMessage`.
- Produces:
```dart
class RideScreen extends StatefulWidget {
  const RideScreen({
    required this.ride, required this.position, required this.onMove,
    required this.onArrive, required this.onConfirmHelmet, required this.onStart, required this.onComplete,
    required this.onAcceptOffer, required this.onDeclineOffer, this.offer, super.key,
  });
  final RiderRide ride;
  final Place position;                       // posição de mentira atual (azul no mapa)
  final void Function(Place) onMove;          // toque no mapa ou atalho
  final Future<void> Function() onArrive, onConfirmHelmet, onComplete;
  final Future<void> Function(String pin) onStart;
  final Offer? offer;                         // oferta que chegou durante a corrida (vai para a fila)
  final Future<void> Function(String rideId) onAcceptOffer, onDeclineOffer;
}
```
Conteúdo por `ride.state`: `accepted` → "Vá buscar {passengerName}", o embarque (texto, se houver), o mapa (`FakeMapView` com `me`, `pickup`, `destination`; o toque chama `onMove`), "Ir até o ponto de embarque" (`onMove(ride.pickup)`) e "Cheguei" (`onArrive`); `arrived` → "Peça o código de 4 dígitos ao passageiro", "Confirmei o capacete extra" (`onConfirmHelmet`; vira "Capacete confirmado" desligado quando `ride.helmetConfirmed`), "Aguardando o Pix do passageiro…" quando `method != 'cash' && !pixPaid`, campo do código (só dígitos, até 4) e "Começar corrida" ligado só com `helmetConfirmed && (method == 'cash' || pixPaid) && código com 4 dígitos`; `inProgress` → "Levando {passengerName}", o destino, o mapa, "Ir até o destino" (`onMove(ride.destination)`) e "Finalizar corrida" (`onComplete`); qualquer outro estado → `SizedBox.shrink()` (o `app.dart` fecha a rota). Mostra sempre o valor (`brl(priceCents)`) e a forma de pagamento. Se `offer != null`, um `OfferCard` no topo. Cada botão que chama a API fica desligado enquanto ela corre; erro → `SnackBar`; um `ApiException` com `code == 'wrong_pin'` também limpa o campo do código.

- [ ] **Step 1: Testes que falham** (`testWidgets`): `'aceita mostra o embarque e cheguei chama onArrive'`; `'ir ate o ponto de embarque manda o pickup para onMove'`; `'tocar no mapa manda um ponto para onMove'`; `'chegou sem capacete: comecar esta desligado mesmo com 4 digitos'`; `'chegou, capacete ok, pix pago e 4 digitos: comecar chama onStart com o codigo'`; `'pix nao pago mostra a espera e desliga o comecar'`; `'corrida em dinheiro nao espera pix'`; `'campo do codigo aceita so digitos e no maximo 4'`; `'wrong_pin mostra a mensagem e limpa o campo'`; `'429 do codigo mostra a mensagem e mantem a tela'`; `'confirmar o capacete chama onConfirmHelmet uma vez mesmo com dois toques'`; `'em viagem mostra finalizar e ele chama onComplete uma vez mesmo com dois toques'`; `'ir ate o destino manda o destination para onMove'`; `'estado completed nao desenha nada'`; `'oferta durante a corrida aparece no topo e aceitar chama onAcceptOffer'`.
- [ ] **Step 2:** `flutter test test/screens/ride_screen_test.dart`. Expected: falha — `ride_screen.dart` não existe.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4:** o teste acima e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela da corrida do motoqueiro`.

---

### Task 11: Navegação (`app.dart`) e `main.dart`

**Files:**
- Create/replace: `mobile/apps/rider/lib/app.dart`, `lib/main.dart`
- Test: `mobile/apps/rider/test/app_test.dart`

**Interfaces:**
- Consumes: `RiderController` (todas as tarefas anteriores), as telas das Tarefas 8–10 e `LoginScreen`/`ChargeScreen`/`RateScreen` de `corrida_ui`.
- Produces:
```dart
class RiderApp extends StatelessWidget { const RiderApp({required this.controller, super.key}); final RiderController controller; }
class SignedInShell extends StatefulWidget { const SignedInShell({required this.controller, super.key}); final RiderController controller; }
```
`RiderApp`: espera (`starting`) → `LoginScreen(onRequestCode: controller.requestCode, onVerify: (phone, code) => controller.verify(phone: phone, code: code))` sem sessão → `SignedInShell(key: ValueKey(session.userId))`. `SignedInShell` tem seu próprio `Navigator` com uma chave. A rota raiz é um `ListenableBuilder` que escolhe por `state.registration.status`: `notRegistered` → `RegistrationScreen` (o `onSubmit` é `controller.registerRider`); `approved` → `HomeScreen`; qualquer outro → `StatusScreen`. `onAcceptOffer` da `HomeScreen` é `controller.accept(id)` e **só depois de dar certo** abre a rota da corrida; `onOpenRide` abre a mesma rota. A rota da corrida é um `ListenableBuilder` que devolve `SizedBox.shrink()` quando `state.ride == null` e, senão, a `RideScreen` ligada às ações do controlador (a oferta durante a corrida vem de `state.offer`). Rota da corrida aberta é fechada quando a corrida some do state (mesmo mecanismo de `_rideRouteOpen` do 6A: só a rota da corrida é desfeita; Cobrar, Pix e Avaliar não). "Enviar novo" abre `RenewDocumentsScreen`, que fecha depois de dar certo. `ChargeScreen` abre por cima com `onDone` fechando. Avisos de `controller.events`:
- `offer` → `HapticFeedback.heavyImpact()` e `SystemSound.play(SystemSoundType.alert)`.
- `trip_completed` → desarma e fecha a rota da corrida (`popUntil` na primeira) e abre `RateScreen` com `onRate: (stars) async { await controller.rate(rideId: id, stars: stars); fechar se der; }` e `onSkip` fechando.
- `ride_cancelled` → fecha a rota da corrida e mostra uma `SnackBar`: `by == 'passenger'` → "O passageiro cancelou a corrida." (+ " Taxa de cancelamento: {brl(fee_cents)}." quando `fee_cents > 0`); `reason == 'pix_expired'` → "O passageiro não pagou o Pix a tempo."; `reason == 'arrival_wait'` → "Passou o tempo de espera no ponto de embarque."; outro → "A corrida foi cancelada."
- `passenger_blocked` → fecha a rota da corrida e "O passageiro foi bloqueado por falta de pagamento. Você está livre."
- `rider_approved` → "Seu cadastro foi aprovado!"; `entry_required` → "Você precisa pagar a entrada para continuar."; `debt_required` → "Você tem uma taxa a pagar para voltar a receber corridas."
`main.dart`: monta `ApiClient`/`AuthApi`/`SessionManager(MemorySessionStore)`/`RiderApi`/`RiderController`, chama `controller.start()` e `runApp(RiderApp(controller: controller))`; `_serverUrl = Uri.parse('http://localhost:8000')` (celular por USB com `adb reverse tcp:8000 tcp:8000`, como no passageiro).

- [ ] **Step 1: Testes que falham** (`app_test.dart`, `testWidgets`; o "mundo" de teste repete o do passageiro: `MockClient` com `stateJson` que o teste muda, `FakeChannel` de `support/fakes.dart`, rotas `POST /v1/auth/code|verify`, `GET /v1/rider/state`, `POST /v1/rider/position`, `POST /v1/rider/online|offers/r1/accept|rides/r1/...`, `POST /v1/rides/r1/rating`, `PUT /v1/rider/documents/...`; cada teste termina com `await tester.runAsync(() => m.controller.signOut())`):
  - `espera enquanto starting e depois mostra o login sem sessao`.
  - `nao cadastrado mostra o cadastro; pendente mostra a espera; aprovado mostra a home`.
  - `rider_approved com a home pendente vira a home` — o state muda para `approved` e o aviso chega: aparece a `HomeScreen` e a `SnackBar` "Seu cadastro foi aprovado!".
  - `aceitar uma oferta abre a tela da corrida` — state com `offer`; ao tocar em "Aceitar", `POST /v1/rider/offers/r1/accept` e, com o state agora trazendo `ride` em `accepted`, aparece a `RideScreen`.
  - `aceitar com 409 offer_gone mostra a mensagem, fica na home e nao abre a corrida` (**Review Focus 1**) — a oferta some do state seguinte; `find.byType(RideScreen)` é `findsNothing` e `find.byType(OfferCard)` também.
  - `passageiro cancelou com a tela da corrida aberta volta para a home com o aviso` (**RF 2**) — aviso `ride_cancelled` `{ride_id:'r1', by:'passenger', fee_cents:300}` com `ride: null` no state seguinte: `RideScreen` some, a frase com `R$ 3,00` aparece; idem `passenger_blocked`.
  - `trip_completed abre avaliar com o ride_id certo e avaliar fecha a tela` — `POST /v1/rides/r1/rating` com `{"stars":1}`; depois `find.byType(RateScreen)` é `findsNothing`.
  - `trip_completed enquanto acompanha mantem a tela de avaliar` — com a `RideScreen` aberta e a releitura do state (`ride: null`) chegando junto, a `RateScreen` fica (o mesmo erro que o 6A pegou na revisão).
  - `cobranca de dinheiro: Recebi o dinheiro manda cash-received`.
  - `entry_required mostra a faixa e Pagar entrada abre o Pix`.
  - `401 volta ao login e a posicao para` (**RF 3**) — state `online:true` e `positionEvery` curto; o state seguinte responde 401; depois de `tester.runAsync` com 3 s: `LoginScreen` na tela e nenhum `POST /v1/rider/position` depois do 401.
  - `aviso offer vibra` — com `SystemChannels.platform` interceptado, o aviso `offer` produz a chamada `HapticFeedback.vibrate`.
- [ ] **Step 2:** `flutter test test/app_test.dart`. Expected: falha — `RiderApp` não existe.
- [ ] **Step 3: Implementar** `app.dart` e `main.dart`.
- [ ] **Step 4:** `flutter test` (todo o app do motoqueiro) e `flutter analyze` em `mobile/`. Expected: passa, sem avisos.
- [ ] **Step 5: Commit** `feat(mobile): navegação e avisos do app do motoqueiro`.

---

### Task 12: Roteiro, notas de teste no celular e suíte inteira

**Files:**
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md` (linha 5 vira "5B … feito"; seção "Itens que sobraram do plano 5B")

- [ ] **Step 1:** rodar tudo a partir de `mobile/`: `dart test` em `packages/corrida_core`, `flutter test` em `packages/corrida_ui`, `apps/passenger`, `apps/rider` e `flutter analyze`. Expected: tudo passa, sem avisos. (O teste de contrato `tool/contrato.sh` não muda.)
- [ ] **Step 2:** atualizar o roteiro: linha do 5B ("feito", com o arquivo do plano e o resumo) e a seção "Itens que sobraram do plano 5B" com: extrato do dia (rota nova no servidor + tela); GPS de verdade, serviço em primeiro plano e tela acesa (plano 7); notificação com o app fechado (Firebase); cadastro recusado não pode reenviar (pergunta para o Levy); SOS do motoqueiro (não há rota); armazenamento seguro do token; `friendlyMessage` ainda não usado nas telas do passageiro; os menores que a revisão final deixar.
- [ ] **Step 3: Como testar no celular** (anotar no roteiro, 5 linhas): servidor e `adb reverse` como em `reference-passenger-app-on-phone`; `cd mobile/apps/rider && flutter run -d <id>`; entrar com um número que não seja o do administrador; preencher o cadastro com as 3 fotos; aprovar o cadastro no painel (`/painel`, fila de cadastros) e tocar em "Atualizar"; para ter corrida, rodar passageiros do simulador (`docs/simulador.md`).
- [ ] **Step 4: Commit** `docs: plano 5B no roteiro (app do motoqueiro)` e `git push`.
