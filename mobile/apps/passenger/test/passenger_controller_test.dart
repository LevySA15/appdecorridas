import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:passenger/passenger_controller.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

http.Response _json(Object? body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Future<void> _deixaRodar() =>
    Future<void>.delayed(const Duration(milliseconds: 20));

class FakeSink implements WebSocketSink {
  var fechado = false;
  final _done = Completer<void>();

  @override
  void add(Object? data) {}

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future<void> addStream(Stream<Object?> stream) => stream.drain();

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    fechado = true;
    if (!_done.isCompleted) _done.complete();
  }

  @override
  Future<void> get done => _done.future;
}

class FakeChannel extends StreamChannelMixin<Object?>
    implements WebSocketChannel {
  FakeChannel(this.uri);

  final Uri uri;
  final _entrada = StreamController<Object?>();
  @override
  final FakeSink sink = FakeSink();
  @override
  int? closeCode;

  void servidorMandaAviso(
    String type, [
    Map<String, Object?>? data,
    double at = 1.0,
  ]) => _entrada.add(jsonEncode({'type': type, 'data': data, 'at': at}));

  @override
  Stream<Object?> get stream => _entrada.stream;

  @override
  Future<void> get ready => Future<void>.value();

  @override
  String? get protocol => null;

  @override
  String? get closeReason => null;
}

class Mundo {
  Mundo() {
    api = ApiClient(baseUrl: baseUrl, httpClient: MockClient(_handle));
    final authApi = AuthApi(api);
    session = SessionManager(authApi, store, api);
    controller = PassengerController(
      authApi: authApi,
      session: session,
      api: PassengerApi(api),
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
  late final PassengerController controller;
  final canais = <FakeChannel>[];

  Map<String, Object?> stateJson = const {};
  int stateStatus = 200;
  var stateThrows = false; // sem internet

  Future<http.Response> _handle(http.Request r) async {
    final path = r.url.path;
    if (r.method == 'POST' && path == '/v1/auth/verify') {
      return _json({
        'token': 'tok-1',
        'user_id': 'u1',
        'role': 'passenger',
        'is_new_user': false,
        'name': null,
      });
    }
    if (r.method == 'GET' && path == '/v1/passenger/state') {
      if (stateThrows) throw http.ClientException('sem rede');
      if (stateStatus != 200) {
        return _json({
          'error': {'code': 'unauthorized', 'message': 'Sessão vencida.'},
        }, stateStatus);
      }
      return _json(stateJson);
    }
    return http.Response('', 404);
  }
}

void main() {
  test('comeca sem sessao guardada fica esperando login', () async {
    final m = Mundo();
    await m.controller.start();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.controller.starting, isFalse);
    expect(m.canais, isEmpty);
  });

  test(
    'comeca com sessao guardada carrega o estado e liga o tempo real',
    () async {
      final m = Mundo();
      await m.store.save(
        Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
      );
      m.stateJson = {'balance_cents': 500};
      await m.controller.start();
      expect(m.controller.state, isNotNull);
      expect(m.controller.state!.balanceCents, 500);
      expect(m.canais.length, 1);
    },
  );

  test(
    'verify com sucesso entra carrega o estado e liga o tempo real',
    () async {
      final m = Mundo();
      await m.controller.start();
      await m.controller.verify(phone: '75988510824', code: '123456');
      expect(m.controller.session, isNotNull);
      expect(m.controller.state, isNotNull);
      expect(m.canais.length, 1);
    },
  );

  test('sign out desliga o tempo real e limpa tudo', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    await m.controller.signOut();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.canais.single.sink.fechado, isTrue);
  });

  test('aviso de tempo real atualiza o estado', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    m.stateJson = {'balance_cents': 999};
    m.canais.single.servidorMandaAviso('balance_changed', {
      'balance_cents': 999,
    });
    await _deixaRodar();
    expect(m.controller.state!.balanceCents, 999);
  });

  test('quem assina events recebe os avisos crus', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    final recebidos = <ServerEvent>[];
    final sub = m.controller.events.listen(recebidos.add);
    m.canais.single.servidorMandaAviso('balance_changed', {
      'balance_cents': 999,
    });
    await _deixaRodar();
    expect(recebidos.single.type, 'balance_changed');
    await sub.cancel();
  });

  test('401 fecha o tempo real e limpa sessao e estado', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    m.stateStatus = 401;
    await expectLater(
      m.controller.refreshState(),
      throwsA(isA<ApiException>()),
    );
    await _deixaRodar();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.canais.single.sink.fechado, isTrue);
  });

  test(
    'abre sem internet com a sessao guardada: termina de iniciar sem estado',
    () async {
      final m = Mundo();
      await m.store.save(
        Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
      );
      m.stateThrows = true;

      await m.controller.start();

      expect(m.controller.starting, isFalse);
      expect(m.controller.session, isNotNull);
      expect(m.controller.state, isNull);
      expect(m.canais.length, 1);
    },
  );

  test(
    'depois de abrir sem internet, tentar de novo carrega o estado',
    () async {
      final m = Mundo();
      await m.store.save(
        Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
      );
      m.stateThrows = true;
      await m.controller.start();
      m.stateThrows = false;

      await m.controller.refreshState();

      expect(m.controller.state, isNotNull);
    },
  );

  test('entrar com a releitura do estado caindo entra mesmo assim', () async {
    final m = Mundo();
    await m.controller.start();
    m.stateThrows = true;
    var avisos = 0;
    m.controller.addListener(() => avisos++);

    await m.controller.verify(phone: '75988510824', code: '123456');

    expect(m.controller.session, isNotNull);
    expect(m.controller.state, isNull);
    expect(avisos, greaterThan(0));
  });
}
