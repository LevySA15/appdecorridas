import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart' show cityCenter;
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'support/mundo.dart';

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

Mundo _mundo(Map<String, Object?> estado) {
  final m = Mundo();
  m.stateJson = estado;
  m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
  return m;
}

int _envios(Mundo m) => m.sent('POST', '/v1/rider/position').length;

Map<String, Object?> _ultimoEnvio(Mundo m) =>
    jsonDecode(m.sent('POST', '/v1/rider/position').last.body)
        as Map<String, Object?>;

void main() {
  test('parado e sem corrida nao envia', () {
    fakeAsync((async) {
      final m = _mundo(_estado());
      m.controller.start();
      async.elapse(const Duration(seconds: 12));
      expect(_envios(m), 0);
    });
  });

  test('disponivel envia na hora e de 4 em 4 segundos', () {
    fakeAsync((async) {
      final m = _mundo(_estado(online: true));
      m.controller.start();
      async.flushMicrotasks();
      expect(_envios(m), 1);
      async.elapse(const Duration(seconds: 8));
      expect(_envios(m), 3);
      expect(_ultimoEnvio(m), {'lat': cityCenter.lat, 'lng': cityCenter.lng});
    });
  });

  test('moveTo muda o que vai no proximo envio', () {
    fakeAsync((async) {
      final m = _mundo(_estado(online: true));
      m.controller.start();
      async.flushMicrotasks();
      expect(m.controller.position.lat, cityCenter.lat);

      m.controller.moveTo(const Place(lat: -12.95, lng: -39.25));
      async.elapse(const Duration(seconds: 4));

      expect(m.controller.position.lat, -12.95);
      expect(_ultimoEnvio(m), {'lat': -12.95, 'lng': -39.25});
    });
  });

  test('em corrida envia mesmo com online false', () {
    fakeAsync((async) {
      final m = _mundo(_estado(comCorrida: true));
      m.controller.start();
      async.elapse(const Duration(seconds: 8));
      expect(_envios(m), 3);
    });
  });

  test('ficar offline para de enviar', () {
    fakeAsync((async) {
      final m = _mundo(_estado(online: true));
      m.on('POST', '/v1/rider/offline', (_) => http.Response('', 204));
      m.controller.start();
      async.flushMicrotasks();

      m.stateJson = _estado();
      m.controller.goOffline();
      async.flushMicrotasks();
      final antes = _envios(m);
      async.elapse(const Duration(seconds: 12));

      expect(_envios(m), antes);
    });
  });

  test('sessao vencida para de enviar', () {
    fakeAsync((async) {
      final m = _mundo(_estado(online: true));
      m.controller.start();
      async.flushMicrotasks();

      m.stateStatus = 401;
      m.controller.refreshState().catchError((Object _) {});
      async.flushMicrotasks();
      expect(m.controller.session, isNull);
      final antes = _envios(m);
      async.elapse(const Duration(seconds: 12));

      expect(_envios(m), antes);
    });
  });

  test('erro de rede no envio nao derruba nem para o ciclo', () {
    fakeAsync((async) {
      final m = _mundo(_estado(online: true));
      var chamadas = 0;
      m.on('POST', '/v1/rider/position', (_) {
        chamadas++;
        if (chamadas == 1) throw http.ClientException('sem rede');
        return http.Response('', 204);
      });
      m.controller.start();
      async.elapse(const Duration(seconds: 8));

      expect(chamadas, 3);
      expect(m.controller.session, isNotNull);
    });
  });
}
