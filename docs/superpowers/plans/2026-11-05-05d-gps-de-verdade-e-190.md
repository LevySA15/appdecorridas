# GPS de verdade, ligar para o 190 e tela acesa (plano 5D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O app do motoqueiro passa a mandar a posição real do GPS (também com o app em segundo plano e a tela acesa) e os dois apps abrem o discador já com o 190 quando alguém aperta o SOS.

**Architecture:** Duas portas novas, no mesmo molde do `PhotoSource` do cadastro: `LocationSource` (GPS) e `ScreenAwake` (tela acesa) no app do motoqueiro, cada uma com uma versão de mentira para testes e para o modo de desenvolvimento e uma versão de verdade (`geolocator`, `wakelock_plus`). `corrida_ui` ganha `dialNumber` (`url_launcher`, `tel:`) usado pelos dois controladores. O `RiderController` continua mandando a posição de 4 em 4 s; só muda de onde vem o ponto.

**Tech Stack:** Flutter 3.47 / Dart, `geolocator`, `wakelock_plus`, `url_launcher`, `flutter_test`.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seção 9, SOS que liga para o 190; seção 4, tela do motoqueiro). Origem: roteiro, "Ainda adiados" do 5B ("GPS de verdade, serviço em primeiro plano e tela sempre acesa") e "Ainda não feito" do 4F (ligar para o 190).

## Global Constraints

- Só Android (iPhone fica para o plano 8). Textos para o usuário em português do Brasil, simples.
- A API do servidor não muda: `POST /v1/rider/position {lat,lng}` a cada 4 s só com o motoqueiro disponível ou numa corrida (regra já existente em `_syncPosition`).
- Nenhuma tela importa `geolocator`, `wakelock_plus` ou `url_launcher`: só os adaptadores e o `main.dart`.
- O discador abre com o número preenchido e a pessoa aperta "ligar" (sem a permissão `CALL_PHONE`).

## Decisões deste plano (minhas, para o Levy conferir)

1. **Modo do GPS:** `--dart-define=GPS=real|fake`; sem a opção, **build de release usa o GPS de verdade e build de depuração (`flutter run`) continua com o mapa de mentira** (tocar no mapa "anda"), para o teste em casa com os passageiros do simulador seguir funcionando.
2. **GPS do passageiro fica fora**: ele só serviria para marcar o embarque, e o mapa de mentira cai no plano 7 (mapa do Google).
3. Com o GPS de verdade, o motoqueiro **não consegue ficar disponível sem a permissão de localização** (mensagem diz o que fazer); se a permissão some com ele já rodando, aparece um aviso no início e a posição para de ir.
4. A tela fica **acesa enquanto o motoqueiro está disponível ou numa corrida**, e apaga o bloqueio ao parar ou sair.
5. O SOS abre o discador **na hora, sem esperar a rede** (o pedido à central segue em paralelo); se o celular não abre o discador, a mensagem "ligue 190" continua valendo.

## Review Focus

- Sem permissão de localização, com o GPS desligado ou com a permissão negada para sempre → não fica disponível, nada vai ao servidor, mensagem diferente para cada caso.
- O GPS só fica ligado (e o serviço em primeiro plano só existe) enquanto o motoqueiro está disponível ou numa corrida; sair, parar e 401 desligam tudo e soltam a tela.
- Posição nova chegando depois de sair da conta não é enviada.
- O discador abre mesmo quando o pedido de SOS ao servidor falha, e uma falha ao abrir o discador não derruba o SOS.
- O manifesto do release leva as permissões de localização/serviço e a consulta de `tel:` (sem elas o release não acha GPS nem discador).

## File Structure

- Create: `mobile/packages/corrida_ui/lib/src/emergency_dialer.dart`, `mobile/apps/rider/lib/location_source.dart`, `mobile/apps/rider/lib/screen_awake.dart`, testes correspondentes
- Modify: `mobile/packages/corrida_ui/lib/corrida_ui.dart`, `mobile/packages/corrida_ui/pubspec.yaml`, `mobile/apps/rider/pubspec.yaml`, os dois `AndroidManifest.xml`, `mobile/apps/rider/lib/rider_controller.dart`, `mobile/apps/rider/lib/main.dart`, `mobile/apps/rider/lib/app.dart`, `mobile/apps/rider/lib/screens/ride_screen.dart`, `mobile/apps/rider/lib/screens/home_screen.dart`, `mobile/apps/passenger/lib/passenger_controller.dart`, `mobile/apps/passenger/lib/main.dart`, `mobile/apps/rider/test/support/mundo.dart`

---

### Task 1: Ligar para o 190 nos dois apps

**Files:**
- Create: `mobile/packages/corrida_ui/lib/src/emergency_dialer.dart`
- Modify: `mobile/packages/corrida_ui/lib/corrida_ui.dart`, `mobile/packages/corrida_ui/pubspec.yaml` (`url_launcher`), os dois `AndroidManifest.xml` (`<queries>` com a ação `DIAL` e o esquema `tel`), `PassengerController.sos`, `RiderController.sos`
- Test: `mobile/packages/corrida_ui/test/emergency_dialer_test.dart`, `mobile/apps/rider/test/rider_actions_test.dart`, `mobile/apps/passenger/test/` (teste do controlador, no arquivo que já cobre as ações), os dois `android_manifest_test.dart`

**Interfaces:**
- Produces: `const emergencyNumber = '190'`; `typedef Dial = Future<bool> Function(String number)`; `Uri dialUri(String number)` (`tel:<número>`); `Future<bool> dialNumber(String number, {Future<bool> Function(Uri uri)? launch})` (`false` se o celular não abre ou se a plataforma levanta erro, nunca levanta); os dois controladores aceitam `Dial dial = dialNumber`.

- [ ] **Step 1: testes que falham.** `dialUri('190').toString() == 'tel:190'`; `dialNumber('190', launch: (_) async => true)` devolve `true` e chama com `tel:190`; com `launch` que levanta `Exception` devolve `false` sem levantar. Controlador do motoqueiro e do passageiro: `sos('r1')` chama o `dial` falso com `'190'` **uma vez** e devolve o resultado do servidor; com o servidor respondendo 500, o `dial` foi chamado e o `sos` ainda levanta o erro do servidor; um `dial` que levanta não impede o resultado. Manifestos: contêm `android.intent.action.DIAL` e `android:scheme="tel"`.
- [ ] **Step 2:** rodar e ver falhar (`cd mobile/packages/corrida_ui && flutter test`; `cd mobile/apps/rider && flutter test test/rider_actions_test.dart`).
- [ ] **Step 3: implementar.** `flutter pub add url_launcher` no `corrida_ui`; `dialNumber` abre com `launchUrl(uri, mode: LaunchMode.externalApplication)`; nos controladores, `sos` dispara `unawaited(dial(emergencyNumber))` (engolindo qualquer erro) **antes** de devolver `api.sos(rideId)`.
- [ ] **Step 4:** rodar os mesmos testes → PASS; `flutter analyze` limpo nos pacotes tocados.
- [ ] **Step 5: Commit** — `feat(mobile): o SOS abre o discador com o 190 nos dois apps`

---

### Task 2: Portas do GPS e da tela acesa

**Files:**
- Create: `mobile/apps/rider/lib/location_source.dart`, `mobile/apps/rider/lib/screen_awake.dart`
- Modify: `mobile/apps/rider/pubspec.yaml` (`geolocator`, `wakelock_plus`), `mobile/apps/rider/android/app/src/main/AndroidManifest.xml`
- Test: `mobile/apps/rider/test/location_source_test.dart`, `mobile/apps/rider/test/android_manifest_test.dart`

**Interfaces:**
- Produces em `location_source.dart`: `enum LocationAccess { granted, denied, deniedForever, serviceOff }`; `abstract class LocationSource { Future<LocationAccess> request(); Stream<Place> positions(); }` (`request` pergunta ao usuário se preciso; `positions` liga o GPS ao ser escutado e desliga ao cancelar; erro do GPS sai como erro do stream); `class FakeLocationSource implements LocationSource` (`request()` → `granted`, `positions()` vazio; é o modo "toque no mapa"); `class GeolocatorLocationSource implements LocationSource` (serviço em primeiro plano com a notificação "Recôncavo Motoqueiro está usando o GPS", precisão alta, filtro de 10 m, a cada 4 s); `LocationAccess accessFrom({required bool serviceEnabled, required LocationPermission permission})` (função pura: serviço desligado → `serviceOff`; `denied`/`unableToDetermine` → `denied`; `deniedForever` → `deniedForever`; `whileInUse`/`always` → `granted`); `bool useRealGps({required String flag, required bool isRelease})` (`'real'` → `true`; `'fake'` → `false`; qualquer outro valor → `isRelease`).
- Produces em `screen_awake.dart`: `abstract class ScreenAwake { Future<void> keepOn(bool on); }`; `WakelockScreenAwake` (usa `wakelock_plus`); `NoScreenAwake` (não faz nada).

- [ ] **Step 1: testes que falham.** `accessFrom` para as cinco combinações acima (inclusive serviço desligado com permissão concedida → `serviceOff`); `useRealGps` para `real`/`fake`/vazio × release/depuração; `FakeLocationSource().request()` é `granted`; manifesto do motoqueiro contém `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`.
- [ ] **Step 2:** rodar e ver falhar (`cd mobile/apps/rider && flutter test test/location_source_test.dart test/android_manifest_test.dart`).
- [ ] **Step 3: implementar** os dois arquivos e as permissões; `flutter pub add geolocator wakelock_plus` no app do motoqueiro. O adaptador do `geolocator` não tem teste de unidade (é só a chamada ao plugin); quem decide fica em `accessFrom`.
- [ ] **Step 4:** testes → PASS; `flutter build apk --debug` do motoqueiro compila com os plugins novos.
- [ ] **Step 5: Commit** — `feat(mobile): portas do GPS e da tela acesa no app do motoqueiro`

---

### Task 3: O controlador do motoqueiro usa o GPS

**Files:**
- Modify: `mobile/apps/rider/lib/rider_controller.dart`, `mobile/apps/rider/test/support/mundo.dart` (aceitar `location`, `screenAwake`, `dial`), `mobile/apps/rider/test/support/fakes.dart` (um `FakeGps` controlável: acesso configurável, `emit(Place)`, `emitError`, conta quantas vezes foi escutado/cancelado; um `FakeScreenAwake` que guarda o último valor)
- Test: `mobile/apps/rider/test/rider_gps_test.dart`

**Interfaces:**
- Consumes: Task 2 (`LocationSource`, `LocationAccess`, `ScreenAwake`).
- Produces: `RiderController({..., LocationSource? location, ScreenAwake? screenAwake, bool realGps = false})`; `bool get usesRealGps`; `String? get locationProblem`; `class LocationUnavailable implements Exception { final String message; }` levantada por `goOnline()` quando o acesso não é `granted`, **antes** de chamar o servidor; `moveTo` não faz nada quando `usesRealGps`.

- [ ] **Step 1: testes que falham** (com `fakeAsync` como em `rider_position_test.dart`):
  - GPS real, disponível: a posição enviada ao servidor é a última emitida pelo `FakeGps`, não o centro da cidade; `moveTo` não muda nada.
  - O GPS só é escutado enquanto disponível ou em corrida; parar (`goOffline`), `signOut` e 401 cancelam a escuta e `keepOn(false)`; ficar disponível faz `keepOn(true)`.
  - `goOnline()` com acesso `denied`, `deniedForever` e `serviceOff` levanta `LocationUnavailable` com três mensagens diferentes ("Permita a localização…", "…nas configurações do celular…", "Ligue o GPS…") e **não** faz `POST /v1/rider/online`.
  - Estado que chega já disponível (o app reabriu) sem permissão: `locationProblem` fica preenchido, nada é enviado, e some quando o GPS volta a emitir.
  - Erro no stream do GPS (`emitError`) preenche `locationProblem` e não derruba o controlador; depois de `signOut`, uma posição emitida não é enviada.
  - GPS de mentira (padrão): comportamento de hoje, todos os testes de `rider_position_test.dart` passam sem mudança.
- [ ] **Step 2:** rodar e ver falhar (`cd mobile/apps/rider && flutter test test/rider_gps_test.dart`).
- [ ] **Step 3: implementar** em `_syncPosition`/`_stopPosition`: ao começar a enviar, escutar `location.positions()` (guardando `_position = place` e limpando `locationProblem`), `await screenAwake.keepOn(true)`; ao parar, cancelar a escuta e `keepOn(false)`. `goOnline` chama `location.request()` primeiro quando `usesRealGps` e traduz o `LocationAccess` na exceção. Mensagens exatas: `denied` "Permita a localização do celular para ficar disponível."; `deniedForever` "A localização está bloqueada. Libere nas configurações do celular para ficar disponível."; `serviceOff` "Ligue o GPS do celular para ficar disponível."; problema em andamento: "Sem sinal de GPS. Você não aparece para os passageiros."
- [ ] **Step 4:** `flutter test` do app inteiro → PASS.
- [ ] **Step 5: Commit** — `feat(mobile): o motoqueiro manda a posição do GPS e mantém a tela acesa`

---

### Task 4: Telas, ligação no `main.dart` e documentação

**Files:**
- Modify: `mobile/apps/rider/lib/screens/ride_screen.dart` (`onMove` passa a ser opcional), `mobile/apps/rider/lib/screens/home_screen.dart` (aviso `locationProblem`), `mobile/apps/rider/lib/app.dart`, `mobile/apps/rider/lib/main.dart`, `mobile/apps/passenger/lib/main.dart` (nada de GPS; só confirmar que compila), `mobile/README.md`
- Test: `mobile/apps/rider/test/screens/ride_screen_test.dart`, `mobile/apps/rider/test/screens/home_screen_test.dart`, `mobile/apps/rider/test/app_test.dart`

**Interfaces:**
- Consumes: Task 3 (`usesRealGps`, `locationProblem`, `LocationUnavailable`).
- Produces: `RideScreen(onMove: void Function(Place)?)`; `HomeScreen(locationProblem: String?)`.

- [ ] **Step 1: testes que falham.** `RideScreen` com `onMove: null`: não mostra "Ir até o ponto de embarque" nem "Ir até o destino" e o mapa não reage a toque; com `onMove` os botões continuam. `HomeScreen` com `locationProblem: 'Sem sinal de GPS…'` mostra o texto; com `null` não mostra nada. `app_test`: tocar em "Estou rodando" com `FakeGps` negado mostra a mensagem da exceção (e o servidor não recebe `/online`); com GPS real a tela da corrida não tem os atalhos de andar.
- [ ] **Step 2:** rodar e ver falhar.
- [ ] **Step 3: implementar.** `app.dart` passa `onMove: _controller.usesRealGps ? null : _controller.moveTo` e `locationProblem: _controller.locationProblem`; `LocationUnavailable` vira o texto do aviso de erro como os outros (`friendlyMessage` ganha o caso). `main.dart`: `const _gps = String.fromEnvironment('GPS')`; `useRealGps(flag: _gps, isRelease: kReleaseMode)` escolhe `GeolocatorLocationSource` + `WakelockScreenAwake` ou `FakeLocationSource` + `NoScreenAwake`. `README.md`: como rodar com GPS de mentira (`flutter run`) e de verdade (`flutter run --dart-define=GPS=real`), o que o aparelho vai pedir, e que o teste em casa com os passageiros do simulador usa o modo de mentira.
- [ ] **Step 4:** `flutter test` e `flutter analyze` dos quatro pacotes; `flutter build apk --debug` dos dois apps.
- [ ] **Step 5: Commit** — `feat(mobile): GPS de verdade no motoqueiro, atalhos de andar só no modo de mentira`

---

### Task 5: Verificação, revisão e entrega

- [ ] **Step 1:** `dart test` em `corrida_core`, `flutter test` em `corrida_ui`, `passenger` e `rider`, `flutter analyze` nos quatro, `mobile/tool/contrato.sh` → tudo verde.
- [ ] **Step 2:** revisão de ponta a ponta do ramo (a minha, a menos que o Levy peça a independente); corrigir o que achar com teste vermelho→verde.
- [ ] **Step 3:** roteiro: linha "5D — feito", seção "Itens que sobraram do plano 5D" (o que só dá para ver no celular de verdade: pedido de permissão, notificação do serviço em primeiro plano, discador, tela acesa; GPS do passageiro e mapa do Google no plano 7; economia de bateria).
- [ ] **Step 4:** mesclar no `main` (avanço simples), rodar os testes do resultado, enviar ao GitHub sem force-push, apagar o ramo e atualizar a memória do projeto.
