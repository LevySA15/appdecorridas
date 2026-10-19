import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

http.Response json(Object? body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json'},
);

class Chamada {
  Chamada(this.method, this.path, this.body);

  final String method;
  final String path;
  final Object? body;

  @override
  String toString() => '$method $path ${body ?? ''}';
}

({PassengerApi api, List<Chamada> chamadas}) mundo(
  http.Response Function(http.Request) responde,
) {
  final chamadas = <Chamada>[];
  final client = ApiClient(
    baseUrl: Uri.parse('http://s.teste'),
    httpClient: MockClient((r) async {
      chamadas.add(
        Chamada(
          r.method,
          r.url.path,
          r.body.isEmpty ? null : jsonDecode(r.body),
        ),
      );
      return responde(r);
    }),
  )..token = 't';
  return (api: PassengerApi(client), chamadas: chamadas);
}

const rua = Place(lat: -12.96, lng: -39.26, text: 'Rua A');
const feira = Place(lat: -12.97, lng: -39.25, text: 'Feira livre');

void main() {
  test('state lê o estado do passageiro', () async {
    final m = mundo(
      (r) => json({
        'balance_cents': 900,
        'payment_methods': ['pix', 'cash'],
      }),
    );
    final estado = await m.api.state();
    expect(estado.balanceCents, 900);
    expect(m.chamadas.single.toString(), 'GET /v1/passenger/state ');
  });

  test('quote manda origem e destino', () async {
    final m = mundo(
      (r) => json({
        'quote_id': 'q1',
        'price_cents': 600,
        'payment_methods': ['pix', 'cash'],
      }),
    );
    final cotacao = await m.api.quote(rua, feira);
    expect(cotacao.quoteId, 'q1');
    expect(m.chamadas.single.method, 'POST');
    expect(m.chamadas.single.path, '/v1/passenger/quotes');
    expect(m.chamadas.single.body, {
      'pickup': rua.toJson(),
      'destination': feira.toJson(),
    });
  });

  test(
    'requestRide manda a cotação e a forma de pagar, inclusive o saldo',
    () async {
      final m = mundo(
        (r) => json({
          'ride_id': 'ride-1',
          'state': 'searching',
          'pay_with_balance': true,
        }, 201),
      );
      final corrida = await m.api.requestRide(quoteId: 'q1', method: 'balance');
      expect(corrida.rideId, 'ride-1');
      expect(corrida.payWithBalance, isTrue);
      expect(m.chamadas.single.path, '/v1/passenger/rides');
      expect(m.chamadas.single.body, {'quote_id': 'q1', 'method': 'balance'});
    },
  );

  test('cancel lê o resultado e codifica o id', () async {
    final m = mundo(
      (r) => json({
        'refund': true,
        'fee_cents': 0,
        'fee': null,
        'refund_to': 'pix',
        'balance_cents': 0,
      }),
    );
    final resultado = await m.api.cancel('ride/1');
    expect(resultado.refund, isTrue);
    expect(m.chamadas.single.path, '/v1/passenger/rides/ride%2F1/cancel');
  });

  test('payFee: saldo cobriu tudo, ou volta a cobrança Pix', () async {
    var cobriu = true;
    final m = mundo(
      (r) => cobriu
          ? json({'paid': true})
          : json({
              'paid': false,
              'charge_id': 'c9',
              'amount_cents': 300,
              'br_code': 'fake-pix|c9|300',
            }),
    );
    final pago = await m.api.payFee();
    expect((pago.paid, pago.charge), (true, null));
    cobriu = false;
    final aPagar = await m.api.payFee();
    expect(aPagar.paid, isFalse);
    expect(
      (
        aPagar.charge!.chargeId,
        aPagar.charge!.amountCents,
        aPagar.charge!.brCode,
      ),
      ('c9', 300, 'fake-pix|c9|300'),
    );
    expect(m.chamadas.first.path, '/v1/passenger/fees/pay');
  });

  test('appealFee manda o texto', () async {
    final m = mundo((r) => http.Response('', 204));
    await m.api.appealFee('ride-1', 'A moto ficou parada.');
    expect(m.chamadas.single.path, '/v1/passenger/rides/ride-1/fee/appeal');
    expect(m.chamadas.single.body, {'text': 'A moto ficou parada.'});
  });

  test('topup e withdraw', () async {
    final m = mundo(
      (r) => r.url.path.endsWith('topup')
          ? json({'charge_id': 'c1', 'amount_cents': 2000, 'br_code': 'x'})
          : json({
              'withdrawal_id': 'wd-1',
              'amount_cents': 1500,
              'balance_cents': 500,
              'key': 'final 4725',
            }, 201),
    );
    final cobranca = await m.api.topup(2000);
    expect((cobranca.chargeId, cobranca.amountCents), ('c1', 2000));
    final saque = await m.api.withdraw(
      amountCents: 1500,
      pixKey: '529.982.247-25',
    );
    expect((saque.withdrawalId, saque.key), ('wd-1', 'final 4725'));
    expect(m.chamadas[0].body, {'amount_cents': 2000});
    expect(m.chamadas[1].path, '/v1/passenger/balance/withdraw');
    expect(m.chamadas[1].body, {
      'amount_cents': 1500,
      'pix_key': '529.982.247-25',
    });
  });

  test(
    'contato de emergência, avaliação, SOS, "está tudo bem" e cobrança',
    () async {
      final m = mundo((r) {
        if (r.url.path.endsWith('/sos')) {
          return json({
            'alert_id': 3,
            'contact_registered': true,
            'contact_notified': true,
            'repeated': false,
            'emergency_number': '190',
          });
        }
        if (r.url.path.startsWith('/v1/charges/'))
          return json({'charge_id': 'c2', 'amount_cents': 700, 'paid': true});
        return http.Response('', 204);
      });
      await m.api.setEmergencyContact(name: 'Maria', phone: '75 98851-0824');
      await m.api.rate('ride-1', 5);
      final sos = await m.api.sos('ride-1');
      await m.api.safetyOk('ride-1', 3);
      final cobranca = await m.api.charge('c2');
      expect(sos.alertId, 3);
      expect(cobranca.paid, isTrue);
      expect(m.chamadas.map((c) => '${c.method} ${c.path}').toList(), [
        'PUT /v1/passenger/emergency-contact',
        'POST /v1/rides/ride-1/rating',
        'POST /v1/rides/ride-1/sos',
        'POST /v1/rides/ride-1/safety/3/ok',
        'GET /v1/charges/c2',
      ]);
      expect(m.chamadas[0].body, {'name': 'Maria', 'phone': '75 98851-0824'});
      expect(m.chamadas[1].body, {'stars': 5});
    },
  );

  test('erros conhecidos chegam com o código', () async {
    for (final codigo in [
      'not_allowed',
      'quote_expired',
      'withdraw_disabled',
      'topup_disabled',
    ]) {
      final m = mundo(
        (r) => json({
          'error': {'code': codigo, 'message': 'frase'},
        }, 403),
      );
      await expectLater(
        m.api.requestRide(quoteId: 'q', method: 'pix'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', codigo)),
      );
    }
  });

  test('resposta fora do formato (lista no lugar do objeto) não estoura erro estranho', () async {
    final m = mundo((r) => json(['lixo']));
    final estado = await m.api.state();
    expect(estado.ride, isNull);
    expect(estado.balanceCents, 0);
  });
}
