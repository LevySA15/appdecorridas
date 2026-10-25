import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import 'app.dart';
import 'passenger_controller.dart';

/// Celular de verdade ligado por USB: `adb reverse tcp:8000 tcp:8000` faz o "localhost" do celular
/// chegar ao servidor do computador pelo cabo, sem precisar da mesma rede Wi-Fi. (Num emulador
/// Android, o endereço seria `10.0.2.2` em vez de `localhost`.)
final _serverUrl = Uri.parse('http://localhost:8000');

void main() {
  // o armazenamento seguro usa canais de plataforma: o Flutter precisa estar de pé antes do `start()`
  WidgetsFlutterBinding.ensureInitialized();
  final client = ApiClient(baseUrl: _serverUrl);
  final authApi = AuthApi(client);
  final session = SessionManager(authApi, SecureSessionStore(), client);
  final controller = PassengerController(
    authApi: authApi,
    session: session,
    api: PassengerApi(client),
    realtimeBaseUrl: _serverUrl,
  );
  controller.start();
  runApp(PassengerApp(controller: controller));
}
