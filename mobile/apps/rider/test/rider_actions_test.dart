import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'support/fakes.dart';
import 'support/mundo.dart';

const _corrida = {
  'ride_id': 'r1',
  'state': 'accepted',
  'price_cents': 700,
  'method': 'pix',
  'passenger': {'name': 'Ana'},
};

Map<String, Object?> _estadoCom({Map<String, Object?>? oferta}) => {
  'registration': {'status': 'approved', 'online': true},
  'account': null,
  'offer': oferta,
  'ride': null,
  'queued_ride': null,
  'awaiting_payment': null,
};

Future<Mundo> _logado() async {
  final m = Mundo();
  m.stateJson = _estadoCom();
  await m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
  await m.controller.start();
  m.requests.clear();
  return m;
}

int _leituras(Mundo m) => m.sent('GET', '/v1/rider/state').length;

void main() {
  final acoes = <(String, String, String, Future<Object?> Function(Mundo))>[
    ('goOnline', 'POST', '/v1/rider/online', (m) => m.controller.goOnline()),
    ('goOffline', 'POST', '/v1/rider/offline', (m) => m.controller.goOffline()),
    (
      'decline',
      'POST',
      '/v1/rider/offers/r1/decline',
      (m) => m.controller.decline('r1'),
    ),
    (
      'arrive',
      'POST',
      '/v1/rider/rides/r1/arrive',
      (m) => m.controller.arrive('r1'),
    ),
    (
      'confirmHelmet',
      'POST',
      '/v1/rider/rides/r1/helmet',
      (m) => m.controller.confirmHelmet('r1'),
    ),
    (
      'completeTrip',
      'POST',
      '/v1/rider/rides/r1/complete',
      (m) => m.controller.completeTrip('r1'),
    ),
    (
      'cashReceived',
      'POST',
      '/v1/rider/rides/r1/cash-received',
      (m) => m.controller.cashReceived('r1'),
    ),
  ];

  for (final (nome, metodo, caminho, chama) in acoes) {
    test('$nome chama $caminho e le o estado de novo', () async {
      final m = await _logado();
      m.on(metodo, caminho, (_) => json(_corrida));
      await chama(m);
      expect(m.sent(metodo, caminho), hasLength(1));
      expect(_leituras(m), 1);
    });
  }

  test('accept devolve a corrida e le o estado de novo', () async {
    final m = await _logado();
    m.on('POST', '/v1/rider/offers/r1/accept', (_) => json(_corrida));
    final ride = await m.controller.accept('r1');
    expect(ride.rideId, 'r1');
    expect(ride.passengerName, 'Ana');
    expect(_leituras(m), 1);
  });

  test('startTrip manda o codigo', () async {
    final m = await _logado();
    m.on('POST', '/v1/rider/rides/r1/start', (_) => json(_corrida));
    await m.controller.startTrip('r1', '1234');
    final corpo = jsonDecode(
      m.sent('POST', '/v1/rider/rides/r1/start').single.body,
    ) as Map<String, Object?>;
    expect(corpo, {'pin': '1234'});
  });

  test('rate manda as estrelas e nao le o estado de novo', () async {
    final m = await _logado();
    m.on('POST', '/v1/rides/r1/rating', (_) => http.Response('', 204));
    await m.controller.rate(rideId: 'r1', stars: 5);
    final corpo = jsonDecode(
      m.sent('POST', '/v1/rides/r1/rating').single.body,
    ) as Map<String, Object?>;
    expect(corpo, {'stars': 5});
    expect(_leituras(m), 0);
  });

  test('cobrancas de entrada, divida e leitura de uma cobranca', () async {
    final m = await _logado();
    const cobranca = {
      'charge_id': 'c1',
      'amount_cents': 5000,
      'br_code': '0002',
    };
    m.on('POST', '/v1/rider/entry-charge', (_) => json(cobranca, 201));
    m.on('POST', '/v1/rider/debt-charge', (_) => json(cobranca, 201));
    m.on('GET', '/v1/charges/c1', (_) => json(cobranca));
    expect((await m.controller.entryCharge()).chargeId, 'c1');
    expect((await m.controller.debtCharge()).amountCents, 5000);
    expect((await m.controller.loadCharge('c1')).brCode, '0002');
  });

  test(
    'accept com 409 offer_gone le o estado de novo e repassa o erro',
    () async {
      final m = Mundo();
      m.stateJson = _estadoCom(oferta: {'ride_id': 'r1', 'price_cents': 700});
      await m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
      await m.controller.start();
      expect(m.controller.state!.offer, isNotNull);

      m.stateJson =
          _estadoCom(); // a oferta venceu enquanto o motoqueiro tocava
      m.on(
        'POST',
        '/v1/rider/offers/r1/accept',
        (_) => json({
          'error': {
            'code': 'offer_gone',
            'message': 'Essa oferta não está mais disponível.',
          },
        }, 409),
      );

      await expectLater(
        m.controller.accept('r1'),
        throwsA(
          isA<ApiException>().having((e) => e.code, 'code', 'offer_gone'),
        ),
      );
      expect(m.controller.state!.offer, isNull);
    },
  );

  test('wrong_pin 422 repassa o erro e le o estado de novo', () async {
    final m = await _logado();
    m.on(
      'POST',
      '/v1/rider/rides/r1/start',
      (_) => json({
        'error': {'code': 'wrong_pin', 'message': 'Código errado.'},
      }, 422),
    );
    await expectLater(
      m.controller.startTrip('r1', '0000'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'wrong_pin')),
    );
    expect(_leituras(m), 1);
    expect(m.controller.state, isNotNull);
  });
}
