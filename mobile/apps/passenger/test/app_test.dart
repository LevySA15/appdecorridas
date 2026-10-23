import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:passenger/app.dart';
import 'package:passenger/passenger_controller.dart';
import 'package:passenger/screens/home_screen.dart';
import 'package:passenger/screens/login_screen.dart';
import 'package:passenger/screens/rate_screen.dart';
import 'package:passenger/screens/ride_screen.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

http.Response _json(Object? body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

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
  http.Request? ratingRequest;

  Future<http.Response> _handle(http.Request r) async {
    final path = r.url.path;
    if (r.method == 'POST' && path == '/v1/auth/code') {
      return http.Response('', 204);
    }
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
      if (stateStatus != 200) {
        return _json({
          'error': {'code': 'unauthorized', 'message': 'Sessão vencida.'},
        }, stateStatus);
      }
      return _json(stateJson);
    }
    if (r.method == 'POST' && path == '/v1/rides/r1/rating') {
      ratingRequest = r;
      return http.Response('', 204);
    }
    return http.Response('', 404);
  }
}

void main() {
  testWidgets('sem sessao mostra login', (tester) async {
    final m = Mundo();
    await m.controller.start();
    await tester.pumpWidget(PassengerApp(controller: m.controller));
    await tester.pump();

    expect(find.byType(LoginScreen), findsOneWidget);
    await tester.runAsync(() => m.controller.signOut());
  });

  testWidgets('login bem sucedido mostra a home', (tester) async {
    final m = Mundo();
    await m.controller.start();
    await tester.pumpWidget(PassengerApp(controller: m.controller));
    await tester.pump();

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('codigo')), '123456');
    await tester.tap(find.text('Entrar'));
    await tester.pumpAndSettle();

    expect(find.byType(HomeScreen), findsOneWidget);
    await tester.runAsync(() => m.controller.signOut());
  });

  testWidgets('sessao vence no meio do uso volta ao login', (tester) async {
    final m = Mundo();
    await m.store.save(
      Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
    );
    await m.controller.start();
    await tester.pumpWidget(PassengerApp(controller: m.controller));
    await tester.pump();

    expect(find.byType(HomeScreen), findsOneWidget);

    m.stateStatus = 401;
    // O aviso de tempo real dispara a releitura automática do estado (em segundo plano); fora do
    // relógio de mentira dos testes, para dar tempo real ao fechamento do tempo real (`.timeout`
    // de verdade em `RealtimeClient._closeChannel`) de terminar antes do fim do teste.
    m.canais.single.servidorMandaAviso('balance_changed', {
      'balance_cents': 0,
    });
    await tester.runAsync(() async {
      await m.controller.refreshState().catchError((_) {});
      await Future<void>.delayed(const Duration(seconds: 3));
    });
    await tester.pump();

    expect(find.byType(LoginScreen), findsOneWidget);
  });

  testWidgets(
    'corrida acaba do outro lado enquanto acompanha volta para a home',
    (tester) async {
      final m = Mundo();
      await m.store.save(
        Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
      );
      m.stateJson = {
        'ride': {'ride_id': 'r1', 'state': 'accepted'},
      };
      await m.controller.start();
      await tester.pumpWidget(PassengerApp(controller: m.controller));
      await tester.pump();

      await tester.tap(find.text('Acompanhar corrida'));
      await tester.pumpAndSettle();
      expect(find.byType(RideScreen), findsOneWidget);

      m.stateJson = const {};
      m.canais.single.servidorMandaAviso('ride_cancelled', {
        'ride_id': 'r1',
      });
      await tester.pumpAndSettle();

      expect(find.byType(RideScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
      await tester.runAsync(() => m.controller.signOut());
    },
  );

  testWidgets(
    'trip_completed enquanto acompanha mantem a tela de avaliar',
    (tester) async {
      final m = Mundo();
      await m.store.save(
        Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
      );
      m.stateJson = {
        'ride': {'ride_id': 'r1', 'state': 'in_progress'},
      };
      await m.controller.start();
      await tester.pumpWidget(PassengerApp(controller: m.controller));
      await tester.pump();

      await tester.tap(find.text('Acompanhar corrida'));
      await tester.pumpAndSettle();
      expect(find.byType(RideScreen), findsOneWidget);

      // a corrida some do estado assim que termina (igual ao servidor de verdade: COMPLETED é
      // terminal e não é "corrida aberta") — ao mesmo tempo que o aviso de tempo real chega.
      m.stateJson = const {};
      m.canais.single.servidorMandaAviso('trip_completed', {
        'ride_id': 'r1',
        'price_cents': 500,
        'method': 'pix',
      });
      await tester.pumpAndSettle();

      expect(find.byType(RateScreen), findsOneWidget);
      await tester.runAsync(() => m.controller.signOut());
    },
  );

  testWidgets('trip_completed abre a tela de avaliar com o ride_id certo', (
    tester,
  ) async {
    final m = Mundo();
    await m.store.save(
      Session(token: 'tok-1', userId: 'u1', role: 'passenger'),
    );
    await m.controller.start();
    await tester.pumpWidget(PassengerApp(controller: m.controller));
    await tester.pump();

    m.canais.single.servidorMandaAviso('trip_completed', {
      'ride_id': 'r1',
      'price_cents': 500,
      'method': 'pix',
    });
    await tester.pumpAndSettle();

    expect(find.byType(RateScreen), findsOneWidget);

    await tester.tap(find.byIcon(Icons.star).first);
    await tester.pumpAndSettle();

    expect(m.ratingRequest, isNotNull);
    expect(jsonDecode(m.ratingRequest!.body), {'stars': 1});
    await tester.runAsync(() => m.controller.signOut());
  });
}
