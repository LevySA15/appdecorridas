import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider/rider_controller.dart';

import 'fakes.dart';

/// Servidor de mentira + controlador do motoqueiro ligados por um `MockClient`. Cada teste muda
/// `stateJson`/`stateStatus` ou registra uma rota com [on]; `requests` guarda tudo que saiu.
class Mundo {
  Mundo() {
    api = ApiClient(baseUrl: baseUrl, httpClient: MockClient(_handle));
    final authApi = AuthApi(api);
    session = SessionManager(authApi, store, api);
    controller = RiderController(
      authApi: authApi,
      session: session,
      api: RiderApi(api),
      realtimeBaseUrl: baseUrl,
      realtimeConnector: (uri) {
        final canal = FakeChannel(uri);
        canais.add(canal);
        return canal;
      },
    );
  }

  final baseUrl = Uri.parse('http://s.teste');
  final store = MemorySessionStore();
  late final ApiClient api;
  late final SessionManager session;
  late final RiderController controller;
  final canais = <FakeChannel>[];
  final requests = <http.Request>[];
  final _routes = <String, http.Response Function(http.Request)>{};

  Map<String, Object?> stateJson = estadoNaoCadastrado;
  int stateStatus = 200;

  /// Troca a resposta de uma rota, por exemplo `on('POST', '/v1/rider/online', (_) => ...)`.
  void on(
    String method,
    String path,
    http.Response Function(http.Request) handler,
  ) => _routes['$method $path'] = handler;

  Iterable<http.Request> sent(String method, String path) =>
      requests.where((r) => r.method == method && r.url.path == path);

  Future<http.Response> _handle(http.Request r) async {
    requests.add(r);
    final key = '${r.method} ${r.url.path}';
    final custom = _routes[key];
    if (custom != null) return custom(r);
    if (key == 'POST /v1/auth/code') return http.Response('', 204);
    if (key == 'POST /v1/auth/verify') {
      return json({
        'token': 'tok-1',
        'user_id': 'u1',
        'role': 'rider',
        'is_new_user': false,
        'name': null,
      });
    }
    if (key == 'GET /v1/rider/state') {
      if (stateStatus != 200) {
        return json({
          'error': {'code': 'unauthorized', 'message': 'Sessão vencida.'},
        }, stateStatus);
      }
      return json(stateJson);
    }
    if (key == 'POST /v1/rider/position') return http.Response('', 204);
    return http.Response('', 404);
  }
}
