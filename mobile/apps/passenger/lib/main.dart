import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'app.dart';
import 'passenger_controller.dart';

/// Emulador Android: 10.0.2.2 chega ao "localhost" do computador que roda o servidor. Num celular de
/// verdade, troque pelo IP do computador na mesma rede.
final _serverUrl = Uri.parse('http://10.0.2.2:8000');

void main() {
  final client = ApiClient(baseUrl: _serverUrl);
  final authApi = AuthApi(client);
  final session = SessionManager(authApi, MemorySessionStore(), client);
  final controller = PassengerController(
    authApi: authApi,
    session: session,
    api: PassengerApi(client),
    realtimeBaseUrl: _serverUrl,
  );
  controller.start();
  runApp(PassengerApp(controller: controller));
}
