import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart' show cityCenter;
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rider/location_source.dart';

import 'support/fakes.dart';
import 'support/mundo.dart';

const _lugar = Place(lat: -12.95, lng: -39.25);
const _outroLugar = Place(lat: -12.94, lng: -39.24);

Map<String, Object?> _estado({bool online = false, bool comCorrida = false}) =>
    {
      'registration': {'status': 'approved', 'online': online},
      'account': null,
      'offer': null,
      'ride': comCorrida
          ? {
              'ride_id': 'r1',
              'state': 'accepted',
              'price_cents': 700,
              'method': 'pix',
              'passenger': {'name': 'Ana'},
            }
          : null,
      'queued_ride': null,
      'awaiting_payment': null,
    };

({Mundo m, FakeGps gps, FakeScreenAwake tela}) _mundo(
  Map<String, Object?> estado, {
  FakeGps? gps,
  bool real = true,
}) {
  final g = gps ?? FakeGps();
  final tela = FakeScreenAwake();
  final m = Mundo(location: g, screenAwake: tela, realGps: real);
  m.stateJson = estado;
  m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
  return (m: m, gps: g, tela: tela);
}

int _envios(Mundo m) => m.sent('POST', '/v1/rider/position').length;

Map<String, Object?> _ultimoEnvio(Mundo m) =>
    jsonDecode(m.sent('POST', '/v1/rider/position').last.body)
        as Map<String, Object?>;

void main() {
  test('com GPS de verdade, o que vai ao servidor é a posição do GPS', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      w.gps.emit(_lugar);
      async.flushMicrotasks();

      expect(_ultimoEnvio(w.m), {'lat': _lugar.lat, 'lng': _lugar.lng});
      w.gps.emit(_outroLugar);
      async.elapse(const Duration(seconds: 4));
      expect(_ultimoEnvio(w.m), {'lat': _outroLugar.lat, 'lng': _outroLugar.lng});
    });
  });

  test('antes do primeiro sinal do GPS não manda posição nenhuma (nunca o centro da cidade)', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.elapse(const Duration(seconds: 12));

      expect(_envios(w.m), 0);
      expect(w.gps.listening, isTrue);
    });
  });

  test('parado no mesmo lugar, repete o último ponto a cada 4 segundos', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      w.gps.emit(_lugar);
      async.flushMicrotasks();
      final antes = _envios(w.m);

      async.elapse(const Duration(seconds: 8));

      expect(_envios(w.m), antes + 2);
      expect(_ultimoEnvio(w.m), {'lat': _lugar.lat, 'lng': _lugar.lng});
    });
  });

  test('moveTo não faz nada com o GPS de verdade', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      w.gps.emit(_lugar);
      async.flushMicrotasks();

      w.m.controller.moveTo(_outroLugar);
      async.elapse(const Duration(seconds: 4));

      expect(w.m.controller.usesRealGps, isTrue);
      expect(w.m.controller.position.lat, _lugar.lat);
      expect(_ultimoEnvio(w.m)['lat'], _lugar.lat);
    });
  });

  test('o GPS e a tela acesa só ficam ligados enquanto disponível ou em corrida', () {
    fakeAsync((async) {
      final w = _mundo(_estado());
      w.m.controller.start();
      async.flushMicrotasks();
      expect(w.gps.listening, isFalse);
      expect(w.tela.last, isNull);

      w.m.stateJson = _estado(online: true);
      w.m.controller.refreshState();
      async.flushMicrotasks();
      expect(w.gps.listening, isTrue);
      expect(w.tela.last, isTrue);

      w.m.stateJson = _estado();
      w.m.controller.refreshState();
      async.flushMicrotasks();
      expect(w.gps.listening, isFalse);
      expect(w.tela.last, isFalse);

      w.m.stateJson = _estado(comCorrida: true);
      w.m.controller.refreshState();
      async.flushMicrotasks();
      expect(w.gps.listening, isTrue);
      expect(w.tela.last, isTrue);
    });
  });

  test('sair da conta desliga o GPS e solta a tela, e posição atrasada não é enviada', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      w.gps.emit(_lugar);
      async.flushMicrotasks();
      final antes = _envios(w.m);

      w.m.controller.signOut();
      async.flushMicrotasks();
      w.gps.emit(_outroLugar);
      async.elapse(const Duration(seconds: 12));

      expect(w.gps.listening, isFalse);
      expect(w.tela.last, isFalse);
      expect(_envios(w.m), antes);
    });
  });

  test('sessão vencida (401) desliga o GPS e solta a tela', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      expect(w.gps.listening, isTrue);

      w.m.stateStatus = 401;
      w.m.controller.refreshState().catchError((Object _) {});
      async.flushMicrotasks();

      expect(w.gps.listening, isFalse);
      expect(w.tela.last, isFalse);
    });
  });

  group('ficar disponível pede a localização', () {
    final casos = {
      LocationAccess.denied: 'Permita a localização do celular para ficar disponível.',
      LocationAccess.deniedForever:
          'A localização está bloqueada. Libere nas configurações do celular para ficar disponível.',
      LocationAccess.serviceOff: 'Ligue o GPS do celular para ficar disponível.',
    };
    for (final MapEntry(key: acesso, value: mensagem) in casos.entries) {
      test('$acesso: não fica disponível e diz o que fazer', () async {
        final w = _mundo(_estado(), gps: FakeGps(access: acesso));
        await w.m.controller.start();

        await expectLater(
          w.m.controller.goOnline(),
          throwsA(
            isA<LocationUnavailable>().having((e) => e.message, 'message', mensagem),
          ),
        );

        expect(w.m.sent('POST', '/v1/rider/online'), isEmpty);
      });
    }

    test('com permissão, fica disponível', () async {
      final w = _mundo(_estado());
      await w.m.controller.start();
      w.m.on('POST', '/v1/rider/online', (_) => http.Response('', 204));

      await w.m.controller.goOnline();

      expect(w.m.sent('POST', '/v1/rider/online'), hasLength(1));
      expect(w.gps.requests, 1);
    });

    test('no modo de mentira não pergunta nada ao GPS', () async {
      final w = _mundo(_estado(), real: false);
      await w.m.controller.start();
      w.m.on('POST', '/v1/rider/online', (_) => http.Response('', 204));

      await w.m.controller.goOnline();

      expect(w.gps.requests, 0);
      expect(w.m.controller.usesRealGps, isFalse);
    });
  });

  test('app reaberto já disponível, mas sem permissão: avisa e não manda nada', () {
    fakeAsync((async) {
      final w = _mundo(
        _estado(online: true),
        gps: FakeGps(access: LocationAccess.deniedForever),
      );
      w.m.controller.start();
      async.elapse(const Duration(seconds: 12));

      expect(w.gps.listening, isFalse);
      expect(_envios(w.m), 0);
      expect(
        w.m.controller.locationProblem,
        'A localização está bloqueada. Libere nas configurações do celular para ficar disponível.',
      );
    });
  });

  test('erro do GPS vira aviso, não derruba, e some quando o sinal volta', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true));
      w.m.controller.start();
      async.flushMicrotasks();
      w.gps.emit(_lugar);
      async.flushMicrotasks();
      expect(w.m.controller.locationProblem, isNull);

      w.gps.emitError(Exception('sem sinal'));
      async.flushMicrotasks();
      expect(
        w.m.controller.locationProblem,
        'Sem sinal de GPS. Você não aparece para os passageiros.',
      );
      expect(w.m.controller.session, isNotNull);

      w.gps.emit(_outroLugar);
      async.flushMicrotasks();
      expect(w.m.controller.locationProblem, isNull);
      expect(_ultimoEnvio(w.m)['lat'], _outroLugar.lat);
    });
  });

  test('no modo de mentira nada muda: começa no centro e anda com moveTo', () {
    fakeAsync((async) {
      final w = _mundo(_estado(online: true), real: false);
      w.m.controller.start();
      async.flushMicrotasks();
      expect(_ultimoEnvio(w.m), {'lat': cityCenter.lat, 'lng': cityCenter.lng});

      w.m.controller.moveTo(_lugar);
      async.elapse(const Duration(seconds: 4));

      expect(_ultimoEnvio(w.m), {'lat': _lugar.lat, 'lng': _lugar.lng});
    });
  });
}
