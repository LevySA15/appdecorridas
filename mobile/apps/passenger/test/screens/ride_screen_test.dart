import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/ride_screen.dart';

const _riderCard = RiderCard(
  riderId: 'rider-1',
  name: 'João',
  plate: 'ABC1234',
  motoModel: 'CG 160',
  rating: 4.8,
  ratingCount: 30,
  photoUrl: null,
);

Widget _app(RideScreen screen) => MaterialApp(home: screen);

RideScreen _screen({
  required PassengerRide ride,
  Future<Charge> Function(String)? onLoadCharge,
  void Function(Charge)? onShowCharge,
  Future<CancelResult> Function()? onCancel,
  Future<SosResult> Function()? onSos,
  Future<void> Function(int)? onSafetyOk,
}) => RideScreen(
  ride: ride,
  onLoadCharge: onLoadCharge ?? (_) async => const Charge(chargeId: 'c', amountCents: 0),
  onShowCharge: onShowCharge ?? (_) {},
  onCancel: onCancel ??
      () async => const CancelResult(
        refund: false,
        feeCents: 0,
        fee: null,
        refundTo: null,
        balanceCents: 0,
      ),
  onSos: onSos ??
      () async => const SosResult(
        alertId: 1,
        contactRegistered: true,
        contactNotified: true,
        repeated: false,
        emergencyNumber: '190',
      ),
  onSafetyOk: onSafetyOk ?? (_) async {},
);

void main() {
  testWidgets('mostra o estado e o pin', (tester) async {
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(
            rideId: 'r1',
            state: RideState.accepted,
            pin: '4821',
            rider: _riderCard,
          ),
        ),
      ),
    );

    expect(find.text('A moto está a caminho'), findsOneWidget);
    expect(find.textContaining('4821'), findsOneWidget);
    expect(find.textContaining('João'), findsOneWidget);
  });

  testWidgets('com pay mostra botao de ver pix e leva a onShowCharge', (
    tester,
  ) async {
    String? idPedido;
    Charge? mostrado;
    final charge = const Charge(chargeId: 'c1', amountCents: 500);
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(
            rideId: 'r1',
            state: RideState.searching,
            pay: PixToPay(chargeId: 'c1', amountCents: 500, expiresAt: 999),
          ),
          onLoadCharge: (id) async {
            idPedido = id;
            return charge;
          },
          onShowCharge: (c) => mostrado = c,
        ),
      ),
    );

    await tester.tap(find.text('Ver Pix'));
    await tester.pumpAndSettle();

    expect(idPedido, 'c1');
    expect(mostrado, charge);
  });

  testWidgets('corrida paga com saldo que passou a ter pix mostra o botao', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(
            rideId: 'r1',
            state: RideState.searching,
            payWithBalance: true,
            pay: PixToPay(chargeId: 'c1', amountCents: 500, expiresAt: 999),
          ),
        ),
      ),
    );

    expect(find.text('Ver Pix'), findsOneWidget);
  });

  testWidgets('cancelar chama onCancel e mostra o resultado', (tester) async {
    var chamado = false;
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(rideId: 'r1', state: RideState.accepted),
          onCancel: () async {
            chamado = true;
            return const CancelResult(
              refund: false,
              feeCents: 300,
              fee: null,
              refundTo: null,
              balanceCents: 0,
            );
          },
        ),
      ),
    );

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    expect(chamado, isTrue);
    expect(find.textContaining('R\$ 3,00'), findsOneWidget);
  });

  testWidgets('sos chama onSos e mostra o numero de emergencia', (
    tester,
  ) async {
    var chamado = false;
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(rideId: 'r1', state: RideState.accepted),
          onSos: () async {
            chamado = true;
            return const SosResult(
              alertId: 1,
              contactRegistered: true,
              contactNotified: true,
              repeated: false,
              emergencyNumber: '190',
            );
          },
        ),
      ),
    );

    await tester.tap(find.text('SOS'));
    await tester.pumpAndSettle();

    expect(chamado, isTrue);
    expect(find.textContaining('190'), findsOneWidget);
  });

  testWidgets(
    'alerta de seguranca presente desde a montagem mostra o dialogo',
    (tester) async {
      await tester.pumpWidget(
        _app(
          _screen(
            ride: const PassengerRide(
              rideId: 'r1',
              state: RideState.inProgress,
              safetyAlert: SafetyAlertRef(alertId: 7, kind: 'stopped'),
            ),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Está tudo bem?'), findsOneWidget);
    },
  );

  testWidgets('tocar esta tudo bem chama onSafetyOk com o alert_id e fecha o dialogo', (
    tester,
  ) async {
    int? alertIdRecebido;
    await tester.pumpWidget(
      _app(
        _screen(
          ride: const PassengerRide(
            rideId: 'r1',
            state: RideState.inProgress,
            safetyAlert: SafetyAlertRef(alertId: 7, kind: 'stopped'),
          ),
          onSafetyOk: (id) async => alertIdRecebido = id,
        ),
      ),
    );
    await tester.pump();

    await tester.tap(find.text('Sim'));
    await tester.pumpAndSettle();

    expect(alertIdRecebido, 7);
    expect(find.text('Está tudo bem?'), findsNothing);
  });
}
