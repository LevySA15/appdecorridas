import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

/// Resposta de `GET /v1/passenger/state` com uma corrida a caminho (forma do `docs/api-v1.md`).
Map<String, Object?> estadoCompleto() => {
      'ride': {
        'ride_id': 'ride-1',
        'state': 'accepted',
        'queued': false,
        'price_cents': 700,
        'price_reason': 'Preço normal para este horário.',
        'method': 'pix',
        'pin': '4821',
        'helmet_confirmed': false,
        'pix_paid': false,
        'pay_with_balance': false,
        'pickup': {'lat': -12.96, 'lng': -39.26, 'text': 'Rua A'},
        'destination': {'lat': -12.97, 'lng': -39.25, 'text': 'Feira livre'},
        'distance_m': 1950,
        'rider': {
          'rider_id': 'r1',
          'name': 'João',
          'plate': 'ABC1D23',
          'moto_model': 'Honda CG 160',
          'rating': 4.8,
          'rating_count': 31,
          'photo_url': '/v1/riders/r1/documents/selfie',
        },
        'rider_position': {'lat': -12.961, 'lng': -39.259},
        'queue': null,
        'safety_alert': {'alert_id': 7, 'kind': 'stopped'},
        'pay': {'charge_id': 'ch-1', 'amount_cents': 700, 'expires_at': 1800000120.5},
        'end_payment': null,
        'cancel': {'free_until': 1800000300.0, 'fee_cents_now': 0},
      },
      'pending_payment': {'ride_id': 'ride-0', 'amount_cents': 600, 'charge_id': 'ch-0', 'blocked': true},
      'blocked_reason': 'Você tem uma taxa para pagar.',
      'unpaid_cents': 300,
      'balance_cents': 1500,
      'topup_enabled': true,
      'pay_with_balance_enabled': true,
      'withdraw_enabled': false,
      'withdraw_min_cents': 500,
      'withdraw_max_cents': 50000,
      'pending_fee': {
        'ride_id': 'ride-0',
        'amount_cents': 300,
        'charge_id': null,
        'appeal': {'state': 'open', 'text': 'A moto parou.', 'appealed_at': 1.0, 'decided_at': null, 'note': null},
      },
      'recent_fees': [
        {
          'ride_id': 'ride-0',
          'fee_cents': 300,
          'created_at': 1800000000.0,
          'from_balance_cents': 0,
          'retained_cents': 0,
          'pending_cents': 300,
          'appeal_state': 'none',
          'can_appeal': true,
        }
      ],
      'emergency_contact': {'name': 'Maria', 'phone': '+5575988510824'},
      'payment_methods': ['pix', 'cash', 'balance'],
    };

void main() {
  test('estado completo do passageiro', () {
    final estado = PassengerState.fromJson(estadoCompleto());
    final corrida = estado.ride!;
    expect(corrida.rideId, 'ride-1');
    expect(corrida.state, RideState.accepted);
    expect((corrida.priceCents, corrida.method, corrida.pin, corrida.payWithBalance), (700, 'pix', '4821', false));
    expect((corrida.pickup.text, corrida.destination.lat), ('Rua A', -12.97));
    expect(corrida.distanceM, 1950);
    expect((corrida.rider!.name, corrida.rider!.plate, corrida.rider!.rating, corrida.rider!.ratingCount), ('João', 'ABC1D23', 4.8, 31));
    expect(corrida.rider!.photoUrl, '/v1/riders/r1/documents/selfie');
    expect(corrida.riderPosition!.lat, -12.961);
    expect((corrida.safetyAlert!.alertId, corrida.safetyAlert!.kind), (7, 'stopped'));
    expect((corrida.pay!.chargeId, corrida.pay!.amountCents, corrida.pay!.expiresAt), ('ch-1', 700, 1800000120.5));
    expect((corrida.cancel!.freeUntil, corrida.cancel!.feeCentsNow), (1800000300.0, 0));
    expect(estado.pendingPayment!.blocked, isTrue);
    expect(estado.blockedReason, 'Você tem uma taxa para pagar.');
    expect((estado.unpaidCents, estado.balanceCents), (300, 1500));
    expect((estado.topupEnabled, estado.payWithBalanceEnabled, estado.withdrawEnabled), (true, true, false));
    expect((estado.withdrawMinCents, estado.withdrawMaxCents), (500, 50000));
    expect(estado.pendingFee!.appeal!.state, 'open');
    expect(estado.pendingFee!.chargeId, isNull);
    expect(estado.recentFees.single.canAppeal, isTrue);
    expect(estado.emergencyContact!.name, 'Maria');
    expect(estado.paymentMethods, ['pix', 'cash', 'balance']);
  });

  test('estado vazio: tudo opcional vira null ou padrão', () {
    final estado = PassengerState.fromJson({});
    expect(estado.ride, isNull);
    expect(estado.pendingPayment, isNull);
    expect(estado.pendingFee, isNull);
    expect(estado.emergencyContact, isNull);
    expect(estado.recentFees, isEmpty);
    expect(estado.paymentMethods, isEmpty);
    expect((estado.balanceCents, estado.unpaidCents), (0, 0));
    expect(estado.withdrawEnabled, isFalse);
  });

  test('corrida com campos ausentes não estoura', () {
    final corrida = PassengerRide.fromJson({'ride_id': 'r', 'state': 'searching'});
    expect(corrida.state, RideState.searching);
    expect(corrida.rider, isNull);
    expect(corrida.pay, isNull);
    expect(corrida.priceCents, 0);
    expect(corrida.pickup.text, '');
  });

  test('estado novo da corrida vira unknown', () {
    expect(PassengerRide.fromJson({'ride_id': 'r', 'state': 'teleporting'}).state, RideState.unknown);
    expect(RideState.parse(null), RideState.unknown);
    expect(RideState.parse('in_progress'), RideState.inProgress);
    expect(RideState.parse('no_rider'), RideState.noRider);
  });

  test('campo novo do servidor é ignorado', () {
    final json = estadoCompleto()..['campo_do_futuro'] = {'a': 1};
    expect(PassengerState.fromJson(json).balanceCents, 1500);
  });

  test('dinheiro vem como inteiro mesmo se o json traz decimal', () {
    final estado = PassengerState.fromJson({'balance_cents': 700.0, 'unpaid_cents': 299.6});
    expect(estado.balanceCents, 700);
    expect(estado.unpaidCents, 300);
  });

  test('corrida na fila traz onde a moto termina', () {
    final corrida = PassengerRide.fromJson({
      'ride_id': 'r',
      'state': 'queued',
      'queued': true,
      'queue': {'finishing_at': 'Praça da Matriz', 'eta_seconds': 240},
    });
    expect(corrida.queued, isTrue);
    expect((corrida.queue!.finishingAt, corrida.queue!.etaSeconds), ('Praça da Matriz', 240));
  });

  test('corrida em dinheiro terminada traz o QR do fim', () {
    final corrida = PassengerRide.fromJson({
      'ride_id': 'r',
      'state': 'completed',
      'method': 'cash',
      'end_payment': {'charge_id': 'ch-9', 'amount_cents': 700, 'blocked': false},
    });
    expect(corrida.endPayment!.chargeId, 'ch-9');
  });

  test('cotação', () {
    final cotacao = Quote.fromJson({
      'quote_id': 'q1',
      'price_cents': 600,
      'distance_m': 1500,
      'duration_s': 180,
      'reason': 'Preço normal para este horário.',
      'expires_at': 1800000300.0,
      'pickup': {'lat': -12.96, 'lng': -39.26, 'text': 'Rua A'},
      'destination': {'lat': -12.97, 'lng': -39.25, 'text': 'Feira livre'},
      'eta_seconds': null,
      'nearby_riders': 0,
      'payment_methods': ['cash'],
    });
    expect((cotacao.quoteId, cotacao.priceCents, cotacao.etaSeconds, cotacao.nearbyRiders), ('q1', 600, null, 0));
    expect(cotacao.paymentMethods, ['cash']);
    expect(cotacao.destination.text, 'Feira livre');
    expect(cotacao.canPayWithBalance, isFalse);
    expect(Quote.fromJson({'payment_methods': ['pix', 'balance']}).canPayWithBalance, isTrue);
  });

  test('resultado do cancelamento', () {
    final resultado = CancelResult.fromJson({
      'refund': true,
      'fee_cents': 400,
      'fee': {'from_balance_cents': 100, 'retained_cents': 300, 'pending_cents': 0},
      'refund_to': 'balance',
      'balance_cents': 400,
    });
    expect((resultado.refund, resultado.feeCents, resultado.refundTo, resultado.balanceCents), (true, 400, 'balance', 400));
    expect((resultado.fee!.fromBalanceCents, resultado.fee!.retainedCents, resultado.fee!.pendingCents), (100, 300, 0));
    final gratis = CancelResult.fromJson({'refund': false, 'fee_cents': 0, 'fee': null, 'refund_to': null, 'balance_cents': 0});
    expect(gratis.fee, isNull);
    expect(gratis.refundTo, isNull);
  });

  test('cobrança, saque e SOS', () {
    final cobranca = Charge.fromJson({'charge_id': 'c1', 'purpose': 'topup', 'ride_id': null, 'amount_cents': 2000, 'paid': false, 'br_code': 'fake-pix|c1|2000'});
    expect((cobranca.chargeId, cobranca.purpose, cobranca.rideId, cobranca.amountCents, cobranca.paid), ('c1', 'topup', null, 2000, false));
    final saque = Withdrawal.fromJson({'withdrawal_id': 'wd-1', 'amount_cents': 1500, 'balance_cents': 500, 'key': 'final 4725'});
    expect((saque.withdrawalId, saque.amountCents, saque.balanceCents, saque.key), ('wd-1', 1500, 500, 'final 4725'));
    final sos = SosResult.fromJson({'alert_id': 3, 'contact_registered': true, 'contact_notified': false, 'repeated': false, 'emergency_number': '190'});
    expect((sos.alertId, sos.contactRegistered, sos.contactNotified, sos.emergencyNumber), (3, true, false, '190'));
  });

  test('lugar vai e volta em json', () {
    const lugar = Place(lat: -12.9, lng: -39.2, text: 'Rua A');
    final volta = Place.fromJson(lugar.toJson());
    expect((volta.lat, volta.lng, volta.text), (-12.9, -39.2, 'Rua A'));
  });
}
