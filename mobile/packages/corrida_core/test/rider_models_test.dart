import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

Map<String, Object?> corridaDoMotoqueiro() => {
  'ride_id': 'ride-1',
  'state': 'accepted',
  'queued': false,
  'price_cents': 700,
  'fee_cents': 100,
  'method': 'cash',
  'pix_paid': false,
  'helmet_confirmed': false,
  'passenger': {'name': 'Ana'},
  'pickup': {'lat': -12.96, 'lng': -39.26, 'text': 'Rua A'},
  'destination': {'lat': -12.97, 'lng': -39.25, 'text': 'Feira livre'},
  'distance_m': 1950,
  'end_payment': {'charge_id': 'ch-1', 'amount_cents': 700, 'blocked': false},
};

void main() {
  test('estado completo do motoqueiro', () {
    final estado = RiderState.fromJson({
      'registration': {
        'status': 'approved',
        'online': true,
        'reason': null,
        'rating': 4.7,
        'rating_count': 12,
        'cnh_expires_on': '2028-05-01',
        'crlv_expires_on': '2027-03-15',
      },
      'account': {
        'completed_rides': 12,
        'trial_rides': 10,
        'entry_paid': true,
        'entry_fee_cents': 5000,
        'needs_entry': false,
        'blocked_reason': 'debt_pending',
        'cash_debt_cents': 100,
        'cash_debt_limit_cents': 70,
        'debt_to_pay_cents': 100,
      },
      'offer': {
        'ride_id': 'ride-2',
        'price_cents': 600,
        'payment_method': 'pix',
        'pickup': {'lat': -12.96, 'lng': -39.26, 'text': 'Rua A'},
        'destination': {'lat': -12.97, 'lng': -39.25, 'text': 'Feira livre'},
        'distance_m': 1500,
        'seconds_to_pickup': 180,
        'will_queue': true,
        'expires_at': 1800000015.0,
      },
      'ride': corridaDoMotoqueiro(),
      'queued_ride': null,
      'awaiting_payment': corridaDoMotoqueiro()..['state'] = 'completed',
    });
    final registro = estado.registration;
    expect(
      (registro.status, registro.online, registro.rating, registro.ratingCount),
      (RegistrationStatus.approved, true, 4.7, 12),
    );
    expect(registro.cnhExpiresOn, DateTime(2028, 5, 1));
    expect(registro.crlvExpiresOn, DateTime(2027, 3, 15));
    final conta = estado.account!;
    expect(
      (
        conta.completedRides,
        conta.trialRides,
        conta.entryPaid,
        conta.entryFeeCents,
      ),
      (12, 10, true, 5000),
    );
    expect(
      (
        conta.blockedReason,
        conta.cashDebtCents,
        conta.cashDebtLimitCents,
        conta.debtToPayCents,
      ),
      ('debt_pending', 100, 70, 100),
    );
    final oferta = estado.offer!;
    expect(
      (
        oferta.rideId,
        oferta.priceCents,
        oferta.paymentMethod,
        oferta.secondsToPickup,
        oferta.willQueue,
      ),
      ('ride-2', 600, 'pix', 180, true),
    );
    expect(oferta.expiresAt, 1800000015.0);
    expect(oferta.pickup.text, 'Rua A');
    expect(estado.ride!.passengerName, 'Ana');
    expect(
      (
        estado.ride!.feeCents,
        estado.ride!.method,
        estado.ride!.endPayment!.chargeId,
      ),
      (100, 'cash', 'ch-1'),
    );
    expect(estado.queuedRide, isNull);
    expect(estado.awaitingPayment!.state, RideState.completed);
  });

  test('motoqueiro sem cadastro', () {
    final estado = RiderState.fromJson({
      'registration': {'status': 'not_registered'},
      'account': null,
      'offer': null,
      'ride': null,
      'queued_ride': null,
      'awaiting_payment': null,
    });
    expect(estado.registration.status, RegistrationStatus.notRegistered);
    expect(estado.account, isNull);
    expect(estado.offer, isNull);
    expect(estado.registration.online, isFalse);
  });

  test('estado vazio ou com situação nova não estoura', () {
    final vazio = RiderState.fromJson({});
    expect(vazio.registration.status, RegistrationStatus.unknown);
    expect(
      RiderState.fromJson({
        'registration': {'status': 'suspenso_por_marte'},
      }).registration.status,
      RegistrationStatus.unknown,
    );
    expect(RegistrationStatus.parse('pending'), RegistrationStatus.pending);
    expect(RegistrationStatus.parse('rejected'), RegistrationStatus.rejected);
    expect(RegistrationStatus.parse('blocked'), RegistrationStatus.blocked);
  });

  test('data inválida de validade vira null', () {
    final registro = RiderRegistration.fromJson({
      'status': 'approved',
      'cnh_expires_on': 'amanhã',
      'crlv_expires_on': null,
    });
    expect(registro.cnhExpiresOn, isNull);
    expect(registro.crlvExpiresOn, isNull);
  });

  test('oferta com campos ausentes', () {
    final oferta = Offer.fromJson({'ride_id': 'r', 'seconds_to_pickup': null});
    expect(
      (
        oferta.rideId,
        oferta.priceCents,
        oferta.secondsToPickup,
        oferta.willQueue,
      ),
      ('r', 0, null, false),
    );
  });

  test('corrida do motoqueiro só traz o primeiro nome', () {
    final corrida = RiderRide.fromJson(corridaDoMotoqueiro());
    expect(corrida.passengerName, 'Ana');
    expect(RiderRide.fromJson({'ride_id': 'r'}).passengerName, '');
  });

  test(
    'formulário de cadastro vira o corpo do servidor com datas AAAA-MM-DD',
    () {
      final formulario = RiderRegistrationForm(
        name: 'João da Silva',
        cpf: '529.982.247-25',
        cnhNumber: '12345678900',
        plate: 'ABC1D23',
        motoModel: 'Honda CG 160',
        selfieKey: 'k-selfie',
        cnhPhotoKey: 'k-cnh',
        crlvKey: 'k-crlv',
        cnhExpiresOn: DateTime(2028, 5, 1),
        crlvExpiresOn: DateTime(2027, 12, 31),
      );
      expect(formulario.toJson(), {
        'name': 'João da Silva',
        'cpf': '529.982.247-25',
        'cnh_number': '12345678900',
        'plate': 'ABC1D23',
        'moto_model': 'Honda CG 160',
        'selfie_key': 'k-selfie',
        'cnh_photo_key': 'k-cnh',
        'crlv_key': 'k-crlv',
        'cnh_expires_on': '2028-05-01',
        'crlv_expires_on': '2027-12-31',
      });
    },
  );

  test('documento enviado', () {
    final documento = UploadedDocument.fromJson({'key': 'k1', 'bytes': 2048});
    expect((documento.key, documento.bytes), ('k1', 2048));
  });

  test('extrato do dia', () {
    final extrato = RiderStatement.fromJson({
      'date': '2026-10-25',
      'completed_count': 2,
      'gross_cents': 1400,
      'fee_cents': 200,
      'net_cents': 1200,
      'cash_cents': 700,
      'pix_cents': 700,
      'rides': [
        {
          'ride_id': 'r1',
          'completed_at': 1761400000.5,
          'price_cents': 700,
          'fee_cents': 100,
          'net_cents': 600,
          'method': 'pix',
          'distance_m': 2300,
        },
      ],
      'next_ride_number': 3,
      'next_fee_cents': 100,
      'cash_debt_cents': 100,
    });

    expect((extrato.date, extrato.completedCount), ('2026-10-25', 2));
    expect(
      (extrato.grossCents, extrato.feeCents, extrato.netCents),
      (1400, 200, 1200),
    );
    expect(
      (extrato.cashCents, extrato.pixCents, extrato.cashDebtCents),
      (700, 700, 100),
    );
    expect((extrato.nextRideNumber, extrato.nextFeeCents), (3, 100));
    final corrida = extrato.rides.single;
    expect(
      (corrida.rideId, corrida.priceCents, corrida.feeCents),
      ('r1', 700, 100),
    );
    expect(
      (corrida.netCents, corrida.method, corrida.distanceM),
      (600, 'pix', 2300),
    );
    expect(corrida.completedAt, 1761400000.5);
  });

  test(
    'extrato de outro dia vem sem proxima faixa e tolera campos que faltam',
    () {
      final extrato = RiderStatement.fromJson({'date': '2026-10-24'});

      expect(extrato.completedCount, 0);
      expect(extrato.rides, isEmpty);
      expect(extrato.nextRideNumber, isNull);
      expect(extrato.nextFeeCents, isNull);
    },
  );
}
