import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:flutter/material.dart';

import 'app.dart';
import 'location_source.dart';
import 'rider_controller.dart';
import 'screen_awake.dart';

/// Celular de verdade ligado por USB: `adb reverse tcp:8000 tcp:8000` faz o "localhost" do celular
/// chegar ao servidor do computador pelo cabo, sem precisar da mesma rede Wi-Fi. (Num emulador
/// Android, o endereço seria `10.0.2.2` em vez de `localhost`.)
/// Servidor de verdade: `--dart-define=API_URL=https://corrida.exemplo.com.br` (ver `mobile/README.md`).
const _apiUrl = String.fromEnvironment('API_URL');
final _serverUrl = serverUrlFrom(_apiUrl, isRelease: kReleaseMode);

/// `--dart-define=GPS=real` usa o GPS do celular, `--dart-define=GPS=fake` deixa "andar" tocando no mapa.
/// Sem a opção: o app de release usa o GPS de verdade e o de depuração (`flutter run`) o de mentira.
const _gps = String.fromEnvironment('GPS');

void main() {
  // o armazenamento seguro usa canais de plataforma: o Flutter precisa estar de pé antes do `start()`
  WidgetsFlutterBinding.ensureInitialized();
  final client = ApiClient(baseUrl: _serverUrl);
  final authApi = AuthApi(client);
  final session = SessionManager(authApi, SecureSessionStore(), client);
  final realGps = useRealGps(flag: _gps, isRelease: kReleaseMode);
  final controller = RiderController(
    authApi: authApi,
    session: session,
    api: RiderApi(client),
    realtimeBaseUrl: _serverUrl,
    realGps: realGps,
    location: realGps ? GeolocatorLocationSource() : FakeLocationSource(),
    screenAwake: realGps ? WakelockScreenAwake() : NoScreenAwake(),
  );
  controller.start();
  runApp(RiderApp(controller: controller));
}
