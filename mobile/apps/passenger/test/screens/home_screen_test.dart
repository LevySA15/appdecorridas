import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/home_screen.dart';

Widget _app(HomeScreen screen) => MaterialApp(home: screen);

void main() {
  testWidgets('com corrida ativa mostra acompanhar', (tester) async {
    var aberto = false;
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            ride: PassengerRide(rideId: 'r1', state: RideState.searching),
          ),
          onRequestRide: () {},
          onOpenRide: () => aberto = true,
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => const PayFeeResult(paid: true),
          onShowPendingCash: (_) async => const Charge(
            chargeId: 'c1',
            amountCents: 100,
          ),
          onShowCharge: (_) {},
        ),
      ),
    );

    expect(find.text('Pedir corrida'), findsNothing);
    await tester.tap(find.text('Acompanhar corrida'));
    expect(aberto, isTrue);
  });

  testWidgets('sem corrida e sem bloqueio mostra pedir', (tester) async {
    var pedido = false;
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(),
          onRequestRide: () => pedido = true,
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => const PayFeeResult(paid: true),
          onShowPendingCash: (_) async =>
              const Charge(chargeId: 'c1', amountCents: 100),
          onShowCharge: (_) {},
        ),
      ),
    );

    await tester.tap(find.text('Pedir corrida'));
    expect(pedido, isTrue);
  });

  testWidgets('bloqueado mostra o motivo sem botao de pedir', (tester) async {
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            blockedReason: 'Pague a corrida pendente para pedir outra.',
          ),
          onRequestRide: () {},
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => const PayFeeResult(paid: true),
          onShowPendingCash: (_) async =>
              const Charge(chargeId: 'c1', amountCents: 100),
          onShowCharge: (_) {},
        ),
      ),
    );

    expect(
      find.text('Pague a corrida pendente para pedir outra.'),
      findsOneWidget,
    );
    expect(find.text('Pedir corrida'), findsNothing);
  });

  testWidgets('pendencia de dinheiro mostra banner e ve o pix', (
    tester,
  ) async {
    String? idPedido;
    Charge? mostrado;
    final charge = const Charge(chargeId: 'c9', amountCents: 500);
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            pendingPayment: PendingPayment(
              rideId: 'r1',
              amountCents: 500,
              chargeId: 'c9',
            ),
          ),
          onRequestRide: () {},
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => const PayFeeResult(paid: true),
          onShowPendingCash: (id) async {
            idPedido = id;
            return charge;
          },
          onShowCharge: (c) => mostrado = c,
        ),
      ),
    );

    await tester.tap(find.text('Ver Pix'));
    await tester.pumpAndSettle();

    expect(idPedido, 'c9');
    expect(mostrado, charge);
  });

  testWidgets(
    'pendencia de dinheiro sem qr ainda nao mostra o botao de ver pix',
    (tester) async {
      await tester.pumpWidget(
        _app(
          HomeScreen(
            state: const PassengerState(
              pendingPayment: PendingPayment(
                rideId: 'r1',
                amountCents: 500,
                // sem charge_id: o motoqueiro ainda não pediu o QR do fim da corrida.
              ),
            ),
            onRequestRide: () {},
            onOpenRide: () {},
            onOpenWallet: () {},
            onSignOut: () {},
            onPayPendingFee: () async => const PayFeeResult(paid: true),
            onShowPendingCash: (_) async =>
                const Charge(chargeId: 'c1', amountCents: 100),
            onShowCharge: (_) {},
          ),
        ),
      );

      expect(find.text('Ver Pix'), findsNothing);
    },
  );

  testWidgets('taxa pendente paga do saldo nao mostra pix', (tester) async {
    Charge? mostrado;
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            pendingFee: PendingFee(rideId: 'r1', amountCents: 300),
          ),
          onRequestRide: () {},
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => const PayFeeResult(paid: true),
          onShowPendingCash: (_) async =>
              const Charge(chargeId: 'c1', amountCents: 100),
          onShowCharge: (c) => mostrado = c,
        ),
      ),
    );

    await tester.tap(find.text('Pagar'));
    await tester.pumpAndSettle();

    expect(mostrado, isNull);
  });

  testWidgets('taxa pendente sem saldo mostra o pix', (tester) async {
    Charge? mostrado;
    final charge = const Charge(chargeId: 'c2', amountCents: 300);
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            pendingFee: PendingFee(rideId: 'r1', amountCents: 300),
          ),
          onRequestRide: () {},
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async =>
              PayFeeResult(paid: false, charge: charge),
          onShowPendingCash: (_) async =>
              const Charge(chargeId: 'c1', amountCents: 100),
          onShowCharge: (c) => mostrado = c,
        ),
      ),
    );

    await tester.tap(find.text('Pagar'));
    await tester.pumpAndSettle();

    expect(mostrado, charge);
  });

  testWidgets('erro ao pagar a taxa mostra a mensagem', (tester) async {
    await tester.pumpWidget(
      _app(
        HomeScreen(
          state: const PassengerState(
            pendingFee: PendingFee(rideId: 'r1', amountCents: 300),
          ),
          onRequestRide: () {},
          onOpenRide: () {},
          onOpenWallet: () {},
          onSignOut: () {},
          onPayPendingFee: () async => throw ApiException(
            status: 409,
            code: 'nothing_to_pay',
            message: 'Não há nada para pagar.',
          ),
          onShowPendingCash: (_) async =>
              const Charge(chargeId: 'c1', amountCents: 100),
          onShowCharge: (_) {},
        ),
      ),
    );

    await tester.tap(find.text('Pagar'));
    await tester.pumpAndSettle();

    expect(find.text('Não há nada para pagar.'), findsOneWidget);
  });
}
