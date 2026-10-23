# App do passageiro (telas e navegação) — Plano de implementação (plano 6A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o aplicativo Flutter do passageiro (`mobile/apps/passenger`): login, pedir corrida, acompanhar a moto, pagar (Pix, dinheiro ou saldo), avaliar, SOS e carteira (saldo/saque/contato de emergência/recurso de taxa) — usando o pacote `corrida_core` do plano 5A, que já tem o cliente da API, a sessão e o tempo real prontos.

**Architecture:** Um `PassengerController` (`ChangeNotifier`) é a única ponte entre as telas e `corrida_core`: guarda a sessão, o último `PassengerState` lido do servidor e a conexão de tempo real, e republica os avisos crus para quem precisar de um (a tela de avaliar, por exemplo, que precisa do `ride_id` de uma corrida que já saiu do `state`). As telas são widgets "burros" — recebem dados e funções de retorno, nunca chamam `Navigator` nem `corrida_core` diretamente — e um único arquivo (`app.dart`) decide, a partir do controlador, qual tela mostrar e quando trocar de uma para outra. Sem mapa de verdade ainda (a chave do Google é plano 7): um "mapa de mentira" desenhado na tela, com a mesma cidade de mentira do simulador do servidor.

**Tech Stack:** Flutter 3.47.7 / Dart 3.13 (já instalados), pacote local `corrida_core` (plano 5A), `flutter_test` para os testes de tela. Nenhum pacote novo.

**Spec:** `docs/api-v1.md` (seções "Passageiro", "Tempo real", "Cobrança", "Códigos de erro") e `docs/superpowers/plans/2026-10-19-05a-base-dos-apps.md` (o pacote que este plano consome). Sem spec de design própria — Levy aprovou as decisões abaixo direto na conversa ("pode ir").

## Global Constraints

- **Dinheiro em centavos inteiros** (`int`); para mostrar, usar `brl(int)` de `corrida_core` — nenhuma tela formata dinheiro na mão.
- **Leitura tolerante** já é garantida pelos modelos de `corrida_core`; as telas só usam os tipos já prontos (`PassengerState`, `PassengerRide`, `Quote`, `Charge` etc.), nunca JSON cru.
- **Token nunca aparece na tela nem em mensagem de erro** — já garantido por `corrida_core`; as telas só mostram `ApiException.message`/`NetworkException.message` (já em português).
- **Papel do login:** `role: "passenger"` (literal; `docs/api-v1.md` linha 21, `server/app/api/routes/auth.py:23`).
- **Centro da cidade de mentira:** `lat: -12.9644, lng: -39.2597` (igual a `server/simulator/geo.py:12`, `CITY_CENTER`). **Caixa do mapa de mentira:** ±3000 m nos dois eixos a partir do centro (decisão deste plano — cobre as zonas do simulador, que vão a ±1600 m).
- **Sem armazenamento seguro de token no celular neste plano** (já adiado no roteiro): usar `MemorySessionStore` de `corrida_core`.
- **Sem pacote novo:** nada de mapa de verdade, QR gráfico, gerência de estado (Provider/Bloc/Riverpod) ou roteador — só `corrida_core`, Flutter e `flutter_test`.
- **Telas são widgets "burros":** recebem dados e `callback`s por parâmetro; nenhuma chama `Navigator` ou importa `PassengerApi`/`RealtimeClient`/`SessionManager` diretamente — só `PassengerController` faz isso, e só `app.dart` decide navegação. Isso é o que deixa cada tela testável sem montar o app inteiro.
- **Toda chamada que pode falhar** (`ApiException`/`NetworkException`) é pega dentro da própria tela, que mostra `e.message` numa `SnackBar`; nenhuma tela trava sem feedback.
- Comentários e textos para a pessoa em português do Brasil, simples; nomes de código em inglês.
- Todos os comandos partem de `mobile/` com `export PATH="$HOME/development/flutter/bin:$PATH"`.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Um comando de git por vez.

## Review Focus

1. **Sessão vence (401) no meio do uso, em qualquer tela** (inclusive acompanhando uma corrida): o app tem que voltar ao login na hora, não deixar a pessoa numa tela morta. Tarefa 10.
2. **Cotação vence antes de confirmar o pedido** (`quote_expired`, 409): a tela de pedir corrida tem que voltar a escolher origem/destino, não tentar de novo com o mesmo `quote_id` vencido. Tarefa 6.
3. **A corrida acaba do outro lado enquanto a pessoa está acompanhando** (`no_rider`, cancelamento pelo motoqueiro, fim da espera na chegada): a tela não pode continuar mostrando botões de uma corrida que não existe mais em `GET /v1/passenger/state`. Tarefa 10.
4. **O alerta de segurança ("está tudo bem?") tem que reaparecer depois de a tela ser reconstruída** (reconexão do tempo real, ou só a pessoa saindo e voltando à tela) — ele vem do `state`, não só da primeira mensagem do socket. Tarefa 7.
5. **Corrida pedida com o saldo que deixa de cobrir até o motoqueiro aceitar** (`balance_short`): a tela de acompanhar tem que saber mostrar o Pix mesmo numa corrida que começou "paga com saldo" (`ride.pay` pode aparecer depois, não só no começo). Tarefa 7.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `mobile/pubspec.yaml` | acrescenta `apps/passenger` ao espaço de trabalho |
| `mobile/apps/passenger/pubspec.yaml` | app Flutter (Android), dependência de caminho para `corrida_core` |
| `.../lib/passenger_controller.dart` | ponte única com `corrida_core`: sessão, estado, tempo real |
| `.../lib/fake_map.dart` | geometria e o widget do mapa de mentira |
| `.../lib/screens/login_screen.dart` | telefone + código |
| `.../lib/screens/home_screen.dart` | bloqueios, pendências, ponto de entrada para pedir/acompanhar |
| `.../lib/screens/request_ride_screen.dart` | mapa de mentira → cotação → forma de pagamento → pedido |
| `.../lib/screens/ride_screen.dart` | acompanhar: estado, motoqueiro, PIN, cancelar, SOS, alerta de segurança |
| `.../lib/screens/charge_screen.dart` | mostrar um Pix para pagar (corrida, taxa, dinheiro do fim, recarga) |
| `.../lib/screens/rate_screen.dart` | avaliar de 1 a 5 estrelas |
| `.../lib/screens/wallet_screen.dart` | saldo, recarga, saque, contato de emergência, recurso de taxa |
| `.../lib/app.dart` | `PassengerApp` e `SignedInShell`: decide a tela e a navegação a partir do controlador |
| `.../lib/main.dart` | monta o `PassengerController` de verdade e chama `runApp` |
| `.../test/**`, `test/screens/**` | testes de tela (`flutter_test`) |

---

### Task 1: Esqueleto do app e `PassengerController`

**Files:**
- Create: `mobile/apps/passenger/pubspec.yaml`, `mobile/apps/passenger/lib/passenger_controller.dart`, `mobile/apps/passenger/lib/main.dart` (versão provisória: `runApp(const MaterialApp(home: SizedBox()))`, sobrescrita na Tarefa 10)
- Modify: `mobile/pubspec.yaml` (acrescenta `apps/passenger` à lista `workspace:`)
- Test: `mobile/apps/passenger/test/passenger_controller_test.dart`

**Interfaces:**
- Consumes (de `corrida_core`): `AuthApi`, `SessionManager`, `SessionStore`, `MemorySessionStore`, `PassengerApi`, `RealtimeClient`, `WebSocketConnector`, `ServerEvent`, `RealtimeStatus`, `Session`, `PassengerState`, `Quote`, `Place`, `CancelResult`, `PayFeeResult`, `SosResult`, `Charge`, `Withdrawal`, `ApiException`, `NetworkException`.
- Produces:
```dart
class PassengerController extends ChangeNotifier {
  PassengerController({
    required AuthApi authApi,
    required SessionManager session,
    required PassengerApi api,
    required Uri realtimeBaseUrl,
    WebSocketConnector? realtimeConnector,
  });

  bool get starting;               // true até o restore() inicial terminar
  Session? get session;
  PassengerState? get state;
  Stream<ServerEvent> get events;  // avisos crus, republicados (quem escuta não perde nenhum desde a assinatura)

  Future<void> start();                                  // restore(); se já tinha sessão, liga o tempo real e lê o state
  Future<void> requestCode(String phone);
  Future<void> verify({required String phone, required String code});
  Future<void> signOut();
  Future<void> refreshState();                            // GET /v1/passenger/state; atualiza `state` e avisa
  Future<Quote> quote(Place pickup, Place destination);
  Future<void> requestRide({required String quoteId, required String method});   // + refreshState()
  Future<CancelResult> cancelRide(String rideId);                                 // + refreshState()
  Future<PayFeeResult> payPendingFee();                                           // + refreshState()
  Future<void> appealFee(String rideId, String text);                             // + refreshState()
  Future<void> rate({required String rideId, required int stars});
  Future<SosResult> sos(String rideId);
  Future<void> safetyOk(String rideId, int alertId);                              // + refreshState()
  Future<Charge> topup(int amountCents);
  Future<Withdrawal> withdraw({required int amountCents, required String pixKey}); // + refreshState()
  Future<void> setEmergencyContact({required String name, required String phone}); // + refreshState()
  Future<Charge> loadCharge(String chargeId);

  @override
  void dispose();  // fecha o tempo real (unawaited) e os streams próprios
}
```
  `requestCode`/`verify` chamam `authApi.requestCode`/`session.signIn(..., role: 'passenger')` (sem guardar nada além do que `SessionManager` já guarda). Depois de um `verify` com sucesso ou de um `start()` que encontrou sessão guardada: ligar o tempo real (`RealtimeClient(baseUrl: realtimeBaseUrl, tokenProvider: () => session.current!.token, connector: realtimeConnector)`, chamar `.start()`) e já chamar `refreshState()` uma vez. Qualquer evento que chegar em `events`/`resync` do `RealtimeClient` dispara um `refreshState()` automático (os avisos são só dicas — a fonte da verdade é o `state`); erro de rede nesse `refreshState()` automático não propaga (ignorado; o próximo aviso tenta de novo). `signOut()` fecha o `RealtimeClient` antes de chamar `session.signOut()` e limpa `state`. O `onUnauthorized` do `ApiClient` (já ligado por dentro do `SessionManager`) acaba emitindo `null` em `session.changes`; o controlador escuta esse stream e, ao ver `null`, fecha o tempo real e limpa `state` (sem chamar rede de novo).

- [ ] **Step 1: Criar o app Flutter e ligar ao espaço de trabalho**

```bash
cd mobile
flutter create --platforms=android --org com.reconcavo --project-name passenger -t app apps/passenger
rm apps/passenger/analysis_options.yaml apps/passenger/*.iml apps/passenger/pubspec.lock apps/passenger/test/widget_test.dart
```
Editar `apps/passenger/pubspec.yaml` para ficar exatamente:
```yaml
name: passenger
description: App do passageiro.
publish_to: none
resolution: workspace
version: 1.0.0+1

environment:
  sdk: ^3.13.0

dependencies:
  flutter:
    sdk: flutter
  corrida_core:
    path: ../../packages/corrida_core

dev_dependencies:
  flutter_test:
    sdk: flutter

flutter:
  uses-material-design: true
```
Acrescentar `- apps/passenger` à lista `workspace:` de `mobile/pubspec.yaml`. Criar `lib/main.dart` provisório (`import 'package:flutter/material.dart'; void main() => runApp(const MaterialApp(home: SizedBox()));`) só para o pacote compilar — a Tarefa 10 substitui.

- [ ] **Step 2: Escrever os testes que falham** (`passenger_controller_test.dart`), usando `ApiClient(baseUrl: Uri.parse('http://s.teste'), httpClient: MockClient(handler))` (pacote `http`, igual aos testes de `corrida_core`) e um `realtimeConnector` de mentira que devolve um canal falso controlável pelo teste (mesmo padrão de `FakeChannel`/`FakeSink` de `corrida_core/test/realtime_test.dart` — pode importar esse arquivo de teste por caminho relativo ou recriar o par mínimo aqui):
  - `comeca_sem_sessao_guardada_fica_esperando_login`: `MemorySessionStore` vazio; depois de `start()`, `controller.session` e `controller.state` são `null`, `controller.starting` é `false`, nenhuma conexão de tempo real foi tentada (o `realtimeConnector` de mentira não foi chamado).
  - `comeca_com_sessao_guardada_carrega_o_estado_e_liga_o_tempo_real`: guardar uma `Session` no `MemorySessionStore` antes de `start()`; o `MockClient` responde ao `GET /v1/passenger/state` com um JSON mínimo válido; depois de `start()`, `controller.state` não é `null` e o `realtimeConnector` foi chamado uma vez.
  - `verify_com_sucesso_entra_carrega_o_estado_e_liga_o_tempo_real`: `MockClient` responde a `POST /v1/auth/verify` e a `GET /v1/passenger/state`; depois de `controller.verify(...)`, `controller.session` não é `null`, `controller.state` não é `null`, tempo real ligado.
  - `sign_out_desliga_o_tempo_real_e_limpa_tudo`: depois de um `verify` bem-sucedido, chamar `signOut()`; `controller.session` e `controller.state` ficam `null`; o canal de mentira foi fechado.
  - `aviso_de_tempo_real_atualiza_o_estado`: depois de conectado, o `MockClient` muda a resposta de `GET /v1/passenger/state`; mandar qualquer mensagem pelo canal de mentira (um JSON `{"type":"algum_aviso","data":{},"at":1.0}`); `controller.state` reflete a nova resposta.
  - `quem_assina_events_recebe_os_avisos_crus`: assinar `controller.events` antes de mandar a mensagem acima pelo canal de mentira; o `ServerEvent` recebido tem `type == 'algum_aviso'`.
  - `401_fecha_o_tempo_real_e_limpa_sessao_e_estado`: depois de conectado, o `MockClient` passa a responder 401 `{"error":{"code":"unauthorized","message":"Sessão vencida."}}` ao próximo `refreshState()` (chamado manualmente pelo teste); `controller.session` e `controller.state` ficam `null` e o canal de mentira foi fechado.

- [ ] **Step 2b:** `flutter test test/passenger_controller_test.dart` (de dentro de `mobile/apps/passenger`). Expected: falha — `PassengerController` não existe.
- [ ] **Step 3: Implementar `PassengerController`** como descrito acima.
- [ ] **Step 4:** `flutter test test/passenger_controller_test.dart` e `flutter analyze`. Expected: passa, sem avisos.
- [ ] **Step 5: Commit** `feat(mobile): esqueleto do app do passageiro e o controlador`.

---

### Task 2: Mapa de mentira

**Files:**
- Create: `mobile/apps/passenger/lib/fake_map.dart`
- Test: `mobile/apps/passenger/test/fake_map_test.dart`

**Interfaces:**
- Consumes: `Place` (de `corrida_core`).
- Produces:
```dart
const cityCenter = Place(lat: -12.9644, lng: -39.2597);
const fakeMapHalfSizeM = 3000.0;

Place pointFromTap(Offset local, Size size);  // pura: um toque dentro do quadrado `size` -> um Place

class FakeMapPicker extends StatefulWidget {
  const FakeMapPicker({required this.onChanged, super.key});
  final void Function(Place? pickup, Place? destination) onChanged;
}
```

`pointFromTap` espelha `offset()` de `server/simulator/geo.py:22-25`: o quadrado de lado `size.shortestSide` representa de −3000 m a +3000 m nos dois eixos, com o centro da tela em `cityCenter`; `eastM` cresce com `local.dx`, `northM` cresce ao contrário de `local.dy` (tela cresce para baixo, norte para cima):
```dart
double _east(Offset local, double side) => (local.dx / side - 0.5) * 2 * fakeMapHalfSizeM;
double _north(Offset local, double side) => (0.5 - local.dy / side) * 2 * fakeMapHalfSizeM;
// lat = cityCenter.lat + graus(northM / earthRadiusM)
// lng = cityCenter.lng + graus(eastM / (earthRadiusM * cos(radianos(cityCenter.lat))))
```
(`earthRadiusM = 6371000.0`, igual ao `EARTH_RADIUS_M` do Python.) `FakeMapPicker` desenha um `CustomPaint` quadrado (fundo de uma cor, uma marca para "Centro"); o primeiro toque marca a origem (pino verde), o segundo marca o destino (pino vermelho); tocar de novo depois dos dois já marcados substitui o destino (permite ajustar sem recomeçar). `Place.text` fica `''` (sem geocodificação nesta etapa). Chama `onChanged(pickup, destination)` a cada mudança.

- [ ] **Step 1: Teste que falha** (`fake_map_test.dart`):
  - `toque_no_centro_do_quadrado_da_o_centro_da_cidade`: `pointFromTap(Offset(50, 50), Size(100, 100))` tem `lat`/`lng` a menos de `1e-6` de `cityCenter.lat`/`cityCenter.lng`.
  - `toque_no_canto_superior_direito_fica_a_nordeste`: `pointFromTap(Offset(100, 0), Size(100, 100))` tem `lat > cityCenter.lat` e `lng > cityCenter.lng`.
  - `widget_test` (`testWidgets`): montar `FakeMapPicker` numa `Size` conhecida dentro de um `MaterialApp`; primeiro `tester.tapAt` chama `onChanged` com `pickup != null, destination == null`; segundo toque chama de novo com os dois não nulos; terceiro toque substitui só o destino (o `pickup` da terceira chamada é igual ao da segunda).
- [ ] **Step 2:** `flutter test test/fake_map_test.dart`. Expected: falha — `fake_map.dart` não existe.
- [ ] **Step 3:** Implementar como descrito.
- [ ] **Step 4:** `flutter test test/fake_map_test.dart` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): mapa de mentira para marcar origem e destino`.

---

### Task 3: Tela de mostrar e pagar um Pix (`ChargeScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/charge_screen.dart`
- Test: `mobile/apps/passenger/test/screens/charge_screen_test.dart`

**Interfaces:**
- Consumes: `Charge` (de `corrida_core`), `brl`.
- Produces:
```dart
class ChargeScreen extends StatelessWidget {
  const ChargeScreen({required this.charge, this.onDone, super.key});
  final Charge charge;
  final VoidCallback? onDone;  // botão "Fechar"/"Já paguei", só aparece se não for nulo
}
```
Mostra o valor (`brl(charge.amountCents)`), um título conforme `charge.purpose` (`ride` → "Pix da corrida", `end` → "Pix da corrida em dinheiro", `fee` → "Pix da taxa de cancelamento", `topup` → "Pix da recarga"; outro valor ou nulo → "Pix a pagar") e o código em `SelectableText` dentro de uma caixa com o rótulo "Pix copia e cola", mais o aviso "Depois de pagar, a tela atualiza sozinha.".

- [ ] **Step 1: Teste que falha**: `testWidgets` — monta `ChargeScreen(charge: Charge(chargeId: 'c1', amountCents: 750, brCode: '00020126...', purpose: 'ride'))` dentro de um `MaterialApp`; encontra o texto `R$ 7,50`, o texto do `br_code` (via `find.text` ou `find.textContaining`) e o título "Pix da corrida"; sem `onDone`, não há botão de fechar; com `onDone`, tocar o botão chama o callback.
- [ ] **Step 2:** `flutter test test/screens/charge_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de mostrar e pagar um Pix`.

---

### Task 4: Tela de login

**Files:**
- Create: `mobile/apps/passenger/lib/screens/login_screen.dart`
- Test: `mobile/apps/passenger/test/screens/login_screen_test.dart`

**Interfaces:**
- Consumes: `ApiException`, `NetworkException`.
- Produces:
```dart
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    required this.onRequestCode,  // Future<void> Function(String phone)
    required this.onVerify,       // Future<void> Function(String phone, String code)
    super.key,
  });
}
```
Dois passos num só formulário: campo de telefone + botão "Enviar código" (chama `onRequestCode`, passa para o passo do código); campo de código (6 dígitos) + botão "Entrar" (chama `onVerify` com o telefone já digitado); botão "Trocar número" volta ao primeiro passo. Erros de qualquer chamada aparecem numa `SnackBar` com `e.message` (pegar `ApiException`/`NetworkException`); enquanto uma chamada está em andamento, o botão correspondente mostra um indicador e fica desabilitado.

- [ ] **Step 1: Teste que falha**: `testWidgets` —
  - `digitar_telefone_e_enviar_chama_onRequestCode`: digitar um telefone, tocar "Enviar código"; `onRequestCode` foi chamado com o telefone digitado; a tela passa a mostrar o campo de código.
  - `digitar_codigo_e_entrar_chama_onVerify_com_telefone_e_codigo`.
  - `erro_do_onRequestCode_mostra_a_mensagem`: `onRequestCode` lança `ApiException(status: 429, code: 'too_many_requests', message: 'Espere um pouco e tente de novo.')`; a `SnackBar` mostra esse texto; a tela continua no primeiro passo.
  - `erro_do_onVerify_mostra_a_mensagem_e_deixa_tentar_de_novo`: `onVerify` lança `ApiException(..., code: 'code_invalid', message: 'Código errado ou vencido.')`; a `SnackBar` mostra o texto; o campo de código continua visível (não volta ao telefone).
- [ ] **Step 2:** `flutter test test/screens/login_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de login do passageiro`.

---

### Task 5: Tela inicial (`HomeScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/home_screen.dart`
- Test: `mobile/apps/passenger/test/screens/home_screen_test.dart`

**Interfaces:**
- Consumes: `PassengerState`, `PayFeeResult`, `Charge`, `brl`, `ApiException`, `NetworkException`.
- Produces:
```dart
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.state,
    required this.onRequestRide,     // VoidCallback
    required this.onOpenRide,        // VoidCallback
    required this.onOpenWallet,      // VoidCallback
    required this.onSignOut,         // VoidCallback
    required this.onPayPendingFee,   // Future<PayFeeResult> Function()
    required this.onShowPendingCash, // Future<Charge> Function(String chargeId)
    required this.onShowCharge,      // void Function(Charge) — chamado quando a tela precisa mostrar um Pix (fee não pago, ou o resultado de onShowPendingCash)
    super.key,
  });
  final PassengerState state;
  // ...
}
```
Regras de exibição (`state.ride` é mutuamente exclusivo com `state.blockedReason`, conforme o servidor): se `state.ride != null`, mostra "Acompanhar corrida" (chama `onOpenRide`); senão, se `state.blockedReason != null`, mostra esse texto sem botão de pedir; senão, mostra "Pedir corrida" (chama `onRequestRide`). Sempre, se presentes: banner de `state.pendingPayment` (valor + botão "Ver Pix" que chama `onShowPendingCash(pendingPayment.chargeId)` e, com o resultado, `onShowCharge`); banner de `state.pendingFee` (valor + botão "Pagar" que chama `onPayPendingFee()` e, se `!result.paid`, `onShowCharge(result.charge!)`); saldo (`brl(state.balanceCents)`) com botão "Carteira" (`onOpenWallet`); botão "Sair" (`onSignOut`). Os dois botões assíncronos (`onPayPendingFee`, `onShowPendingCash`) mostram indicador de carregamento e pegam erro numa `SnackBar` com `e.message`.

- [ ] **Step 1: Teste que falha**: `testWidgets` —
  - `com_corrida_ativa_mostra_acompanhar`: `state.ride != null` → botão "Acompanhar corrida" chama `onOpenRide`; não há botão "Pedir corrida".
  - `sem_corrida_e_sem_bloqueio_mostra_pedir`: `onRequestRide` chamado ao tocar "Pedir corrida".
  - `bloqueado_mostra_o_motivo_sem_botao_de_pedir`: `state.blockedReason == 'Pague a corrida pendente para pedir outra.'` → o texto aparece; não há botão "Pedir corrida".
  - `pendencia_de_dinheiro_mostra_banner_e_ve_o_pix`: `state.pendingPayment != null`; tocar "Ver Pix" chama `onShowPendingCash` com o `charge_id`; o `Charge` devolvido é passado para `onShowCharge`.
  - `taxa_pendente_paga_do_saldo_nao_mostra_pix`: `onPayPendingFee` devolve `PayFeeResult(paid: true)`; `onShowCharge` não é chamado.
  - `taxa_pendente_sem_saldo_mostra_o_pix`: `onPayPendingFee` devolve `PayFeeResult(paid: false, charge: ...)`; `onShowCharge` é chamado com esse `Charge`.
  - `erro_ao_pagar_a_taxa_mostra_a_mensagem`.
- [ ] **Step 2:** `flutter test test/screens/home_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela inicial do passageiro`.

---

### Task 6: Pedir corrida (`RequestRideScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/request_ride_screen.dart`
- Test: `mobile/apps/passenger/test/screens/request_ride_screen_test.dart`

**Interfaces:**
- Consumes: `FakeMapPicker` (Tarefa 2), `Place`, `Quote`, `brl`, `ApiException`.
- Produces:
```dart
class RequestRideScreen extends StatefulWidget {
  const RequestRideScreen({
    required this.onQuote,    // Future<Quote> Function(Place pickup, Place destination)
    required this.onConfirm,  // Future<void> Function(String quoteId, String method)
    super.key,
  });
}
```
Três passos internos: **marcando** (mostra `FakeMapPicker`; quando os dois pontos são marcados, chama `onQuote` automaticamente e passa para **cotado**); **cotado** (mostra preço `brl(quote.priceCents)`, distância, prazo estimado, e um seletor de forma de pagamento com as opções de `quote.paymentMethods` — rótulos "Pix", "Dinheiro", "Saldo" — e um botão "Pedir corrida" que chama `onConfirm(quote.quoteId, método_escolhido)`); erro do `onConfirm` com `code == 'quote_expired'` volta para **marcando** com a mensagem "Essa cotação venceu, marque de novo." numa `SnackBar`; qualquer outro erro mostra `e.message` numa `SnackBar` sem mudar de passo. Erro do `onQuote` mostra `e.message` e continua em **marcando** (os pontos somem, para marcar de novo).

- [ ] **Step 1: Teste que falha**: `testWidgets` —
  - `marcar_os_dois_pontos_pede_a_cotacao_e_mostra_o_preco`: simular os dois toques do `FakeMapPicker`; `onQuote` foi chamado; o preço devolvido aparece na tela.
  - `escolher_pagamento_e_confirmar_chama_onConfirm_com_o_metodo_certo`.
  - `cotacao_so_oferece_saldo_quando_o_quote_permite`: `Quote.paymentMethods == ['pix', 'cash']` → não há opção "Saldo" na tela.
  - `cotacao_vencida_ao_confirmar_volta_a_marcar`: `onConfirm` lança `ApiException(status: 409, code: 'quote_expired', message: '...')`; depois do erro, a tela volta a mostrar o `FakeMapPicker` (não o preço antigo).
  - `erro_de_rede_na_cotacao_mostra_mensagem_e_deixa_marcar_de_novo`.
- [ ] **Step 2:** `flutter test test/screens/request_ride_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de pedir corrida`.

---

### Task 7: Acompanhar corrida (`RideScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/ride_screen.dart`
- Test: `mobile/apps/passenger/test/screens/ride_screen_test.dart`

**Interfaces:**
- Consumes: `PassengerRide`, `RideState`, `CancelResult`, `SosResult`, `Charge`, `brl`, `ApiException`.
- Produces:
```dart
class RideScreen extends StatefulWidget {
  const RideScreen({
    required this.ride,
    required this.onLoadCharge,  // Future<Charge> Function(String chargeId) — para mostrar ride.pay
    required this.onShowCharge,  // void Function(Charge)
    required this.onCancel,      // Future<CancelResult> Function()
    required this.onSos,         // Future<SosResult> Function()
    required this.onSafetyOk,    // Future<void> Function(int alertId)
    super.key,
  });
  final PassengerRide ride;
}
```
Mostra o estado (`ride.state`, um texto por valor: `searching` "Procurando moto...", `queued` "Na fila...", `accepted`/`arrived` "A moto está a caminho", `inProgress` "Em viagem"), o PIN (`ride.pin`) quando há motoqueiro, a ficha do motoqueiro (`ride.rider`: nome, placa, modelo, nota) quando não nula, um botão "Ver Pix" quando `ride.pay != null` (chama `onLoadCharge(ride.pay!.chargeId)` e o resultado vai para `onShowCharge`), um botão "Ver Pix" quando `ride.endPayment != null` (idem, com `ride.endPayment!.chargeId`, só se não nulo), um botão "Cancelar" (chama `onCancel`, mostra o resultado — taxa cobrada ou não — numa `SnackBar` ou diálogo simples) e um botão "SOS" (chama `onSos`, mostra `emergencyNumber` e se o contato foi avisado). Quando `ride.safetyAlert != null` e ainda não foi mostrado o diálogo **para esse `alert_id`** (comparação guardada num campo de estado do widget, não num listener de evento — para reaparecer mesmo numa tela recém-montada depois de reconectar), mostra um `AlertDialog` "Está tudo bem?" com um botão "Sim" que chama `onSafetyOk(ride.safetyAlert!.alertId)` e fecha o diálogo.

- [ ] **Step 1: Teste que falha**: `testWidgets` —
  - `mostra_o_estado_e_o_pin`.
  - `com_pay_mostra_botao_de_ver_pix_e_leva_a_onShowCharge`: `ride.pay != null`; tocar "Ver Pix" chama `onLoadCharge` com o `charge_id` certo e passa o resultado para `onShowCharge`.
  - `corrida_paga_com_saldo_que_passou_a_ter_pix_mostra_o_botao`: `ride` com `payWithBalance: true` **e** `pay != null` ao mesmo tempo (o caso do `balance_short`) — o botão "Ver Pix" aparece do mesmo jeito que numa corrida comum.
  - `cancelar_chama_onCancel_e_mostra_o_resultado`.
  - `sos_chama_onSos_e_mostra_o_numero_de_emergencia`.
  - `alerta_de_seguranca_presente_desde_a_montagem_mostra_o_dialogo`: montar a tela já com `ride.safetyAlert != null` (sem passar por nenhum evento) — o diálogo aparece depois do primeiro `pump`. Isso prova a Review Focus 4: a tela não depende de um evento ao vivo para desenhar o diálogo.
  - `tocar_esta_tudo_bem_chama_onSafetyOk_com_o_alert_id_e_fecha_o_dialogo`.
- [ ] **Step 2:** `flutter test test/screens/ride_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de acompanhar a corrida`.

---

### Task 8: Avaliar (`RateScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/rate_screen.dart`
- Test: `mobile/apps/passenger/test/screens/rate_screen_test.dart`

**Interfaces:**
- Produces:
```dart
class RateScreen extends StatelessWidget {
  const RateScreen({required this.onRate, required this.onSkip, super.key});
  final Future<void> Function(int stars) onRate;  // 1 a 5
  final VoidCallback onSkip;                      // "Agora não"
}
```
Cinco estrelas tocáveis; tocar uma estrela chama `onRate(n)` (mostra indicador enquanto espera; erro numa `SnackBar`, sem sair da tela); botão "Agora não" chama `onSkip` direto.

- [ ] **Step 1: Teste que falha**: `testWidgets` — tocar a 4ª estrela chama `onRate(4)`; tocar "Agora não" chama `onSkip`; erro do `onRate` mostra `e.message` e continua na tela.
- [ ] **Step 2:** `flutter test test/screens/rate_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de avaliar a corrida`.

---

### Task 9: Carteira (`WalletScreen`)

**Files:**
- Create: `mobile/apps/passenger/lib/screens/wallet_screen.dart`
- Test: `mobile/apps/passenger/test/screens/wallet_screen_test.dart`

**Interfaces:**
- Consumes: `PassengerState`, `RecentFee`, `Charge`, `Withdrawal`, `brl`, `ApiException`.
- Produces:
```dart
class WalletScreen extends StatefulWidget {
  const WalletScreen({
    required this.state,
    required this.onTopup,                 // Future<Charge> Function(int amountCents)
    required this.onWithdraw,               // Future<Withdrawal> Function(int amountCents, String pixKey)
    required this.onSetEmergencyContact,    // Future<void> Function(String name, String phone)
    required this.onAppealFee,              // Future<void> Function(String rideId, String text)
    required this.onShowCharge,             // void Function(Charge)
    super.key,
  });
}
```
Mostra `brl(state.balanceCents)`; se `state.topupEnabled`, botão "Recarregar" abre um formulário de valor e chama `onTopup`, passando o resultado para `onShowCharge`; se `state.withdrawEnabled`, botão "Sacar" abre um formulário de valor + chave Pix e chama `onWithdraw`, mostra a confirmação (`withdrawal_id`, novo saldo); formulário de contato de emergência (nome + telefone, preenchido com `state.emergencyContact` quando houver) que chama `onSetEmergencyContact`; lista de `state.recentFees` (valor, data, situação do recurso) com botão "Pedir recurso" quando `fee.canAppeal` — abre um campo de texto e chama `onAppealFee(fee.rideId, texto)`. Cada ação assíncrona pega erro numa `SnackBar` com `e.message`.

- [ ] **Step 1: Teste que falha**: `testWidgets` —
  - `recarga_desligada_nao_mostra_o_botao` / `recarga_ligada_chama_onTopup_e_mostra_o_pix`.
  - `saque_desligado_nao_mostra_o_botao` / `saque_chama_onWithdraw_com_valor_e_chave`.
  - `salvar_contato_de_emergencia_chama_onSetEmergencyContact`.
  - `taxa_recente_com_recurso_permitido_mostra_o_botao_e_chama_onAppealFee_com_o_texto`.
  - `taxa_recente_sem_recurso_permitido_nao_mostra_o_botao`.
  - `erro_ao_sacar_mostra_a_mensagem`.
- [ ] **Step 2:** `flutter test test/screens/wallet_screen_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `flutter test ...` e `flutter analyze`. Expected: passa.
- [ ] **Step 5: Commit** `feat(mobile): tela de carteira do passageiro`.

---

### Task 10: `app.dart` — navegação e o app de verdade

**Files:**
- Create: `mobile/apps/passenger/lib/app.dart`
- Modify: `mobile/apps/passenger/lib/main.dart` (monta o `PassengerController` de verdade com `ApiClient`/`AuthApi`/`SessionManager`/`PassengerApi` apontando para a URL do servidor e chama `runApp(PassengerApp(controller: controller))`)
- Test: `mobile/apps/passenger/test/app_test.dart`

**Interfaces:**
- Consumes: todas as telas das Tarefas 3-9, `PassengerController` (Tarefa 1), `ServerEvent`, `asString` (de `corrida_core`, leitura tolerante do `data` de um `ServerEvent`).
- Produces:
```dart
class PassengerApp extends StatelessWidget {
  const PassengerApp({required this.controller, super.key});
  final PassengerController controller;
}
```
`PassengerApp` é um `MaterialApp` com `home` definido por um `ListenableBuilder(listenable: controller, ...)`: enquanto `controller.starting`, uma tela de carregamento; sem `controller.session`, `LoginScreen(onRequestCode: controller.requestCode, onVerify: ...)`; senão, `SignedInShell(controller: controller, key: ValueKey(controller.session!.userId))`. `SignedInShell` (`StatefulWidget`) guarda um `GlobalKey<NavigatorState>` e um `Navigator` próprio cuja primeira rota é a `HomeScreen` ligada ao controlador (os `callback`s de `HomeScreen`/`RequestRideScreen`/`RideScreen`/`WalletScreen` chamam os métodos do `PassengerController` e, quando preciso mostrar um `Charge`, empurram `ChargeScreen` na própria pilha). A rota empurrada por `onOpenRide` **não** é um `RideScreen` com um `ride` fixo: é um `ListenableBuilder(listenable: controller, builder: (_, __) => RideScreen(ride: controller.state!.ride!, ...))`, para que cada aviso de tempo real que muda `controller.state` redesenhe a tela com a corrida atual — é essa mesma reconstrução que faz o diálogo de segurança (Tarefa 7) reaparecer e que dá ao `_onControllerChanged` abaixo algo a que reagir. Em `initState`, assina `controller.addListener(_onControllerChanged)` e `controller.events.listen(_onEvent)`: `_onControllerChanged` dá `popUntil((r) => r.isFirst)` se a pilha não estiver na primeira rota e `controller.state?.ride == null` (a corrida acabou ou foi cancelada do outro lado enquanto a pessoa acompanhava); `_onEvent` com `event.type == 'trip_completed'` empurra `RateScreen(onRate: (stars) => controller.rate(rideId: asString(event.data['ride_id']), stars: stars), onSkip: () => navigatorKey.currentState!.pop())`. Em `dispose`, cancela a assinatura de `events` e remove o listener (não chama `controller.dispose()` — o dono do controlador é `main.dart`).

- [ ] **Step 1: Teste que falha** (`app_test.dart`), usando um `PassengerController` de verdade com `ApiClient(httpClient: MockClient(...))` e um `realtimeConnector`/canal de mentira controlável pelo teste (mesmo padrão da Tarefa 1):
  - `sem_sessao_mostra_login`.
  - `login_bem_sucedido_mostra_a_home`: completar telefone+código na `LoginScreen` montada pelo `PassengerApp`; depois do `verify`, a tela muda para `HomeScreen` sozinha (o `ListenableBuilder` reage à mudança de `controller.session`).
  - `sessao_vence_no_meio_do_uso_volta_ao_login`: começar autenticado (sessão guardada) e numa tela qualquer depois do login; o `MockClient` devolve 401 num `refreshState` disparado por um aviso de tempo real; a tela volta a `LoginScreen` sozinha, de qualquer tela em que a pessoa estivesse (prova a Review Focus 1).
  - `corrida_acaba_do_outro_lado_enquanto_acompanha_volta_para_a_home`: estado inicial com uma corrida ativa, abrir `RideScreen` (tocando "Acompanhar corrida" na Home); um aviso de tempo real chega e o `MockClient` passa a responder `GET /v1/passenger/state` sem `ride`; depois do `refreshState` automático, a tela volta para `HomeScreen` sozinha (prova a Review Focus 3).
  - `trip_completed_abre_a_tela_de_avaliar_com_o_ride_id_certo`: mandar pelo canal de mentira `{"type":"trip_completed","data":{"ride_id":"r1","price_cents":500,"method":"pix"},"at":1.0}`; a tela de avaliar aparece; tocar uma estrela chama `POST /v1/rides/r1/rating` (conferir pelo que o `MockClient` recebeu).
- [ ] **Step 2:** `flutter test test/app_test.dart`. Expected: falha.
- [ ] **Step 3:** Implementar `app.dart` e o `main.dart` de verdade.
- [ ] **Step 4:** `flutter test` (a suíte inteira do app) e `flutter analyze`. Expected: tudo passa, sem avisos.
- [ ] **Step 5: Commit** `feat(mobile): navegação e o app do passageiro de verdade`.

---

## Depois de todas as tarefas

1. Rodar `flutter test` e `flutter analyze` em `mobile/apps/passenger` (suíte inteira) e `dart test`/`dart analyze` em `packages/corrida_core` (garantir que nada quebrou lá).
2. Revisão final: dispatch de um revisor novo (modelo mais capaz disponível) no branch inteiro, seguindo `superpowers:executing-plans` — pacote da revisão com `review-package`, achados Critical/Important corrigidos nesta mesma sessão com teste RED→GREEN, achados Minor registrados no ledger e citados aqui como "Itens que sobraram".
3. Acrescentar uma linha ao roteiro (`docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`), na tabela de fases, marcando o plano 6A como feito (nos mesmos moldes das linhas dos planos 4E e 5A) e citando o que ficou de fora deste plano (ver abaixo).
4. Merge para `main` (fast-forward), push, apagar o workspace deste plano.

**Fora deste plano (fica para depois, mesmo padrão do roteiro):** mapa de verdade (chave do Google, plano 7); notificações (Firebase); foto por câmera e envio de documentos (é do app do motoqueiro, plano 5B); armazenamento seguro do token no celular; tradução de textos; qualquer aviso de tempo real que não seja `trip_completed` ganhando uma reação própria na tela (por exemplo, um toast para `ride_cancelled` iniciado pelo motoqueiro) — por ora todos os outros avisos só releem o `state`, que já é suficiente para redesenhar a tela certa.
