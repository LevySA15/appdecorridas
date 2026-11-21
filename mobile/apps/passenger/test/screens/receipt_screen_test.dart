import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/receipt_screen.dart';

RideHistoryItem _item({
  RideState state = RideState.completed,
  HistoryRider? rider = const HistoryRider(
    name: 'João',
    plate: 'ABC1D23',
    motoModel: 'Honda CG 160',
  ),
  int? stars,
  int fee = 0,
  bool refunded = false,
  bool pending = false,
  String method = 'pix',
  String pickup = 'Rua A',
  String destination = 'Feira livre',
}) => RideHistoryItem(
  rideId: 'r1',
  state: state,
  createdAt: DateTime(2026, 11, 20, 18, 5).millisecondsSinceEpoch / 1000,
  priceCents: 700,
  method: method,
  pickupText: pickup,
  destinationText: destination,
  distanceM: 1950,
  rider: rider,
  myStars: stars,
  feeCents: fee,
  feeRefunded: refunded,
  paymentPending: pending,
);

Widget _app(RideHistoryItem ride) =>
    MaterialApp(home: ReceiptScreen(ride: ride));

void main() {
  testWidgets('corrida concluida mostra total, motoqueiro, nota e distancia', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_item(stars: 4)));

    expect(find.text('20/11/2026 18:05'), findsOneWidget);
    expect(find.text('Concluída'), findsOneWidget);
    expect(find.text('Rua A'), findsOneWidget);
    expect(find.text('Feira livre'), findsOneWidget);
    expect(find.text('1,9 km'), findsOneWidget);
    expect(find.text('Total'), findsOneWidget);
    expect(find.text(brl(700)), findsOneWidget);
    expect(find.text('João · ABC1D23 · Honda CG 160'), findsOneWidget);
    expect(find.text('Pix'), findsOneWidget);
    expect(find.text('4 de 5'), findsOneWidget);
    expect(find.text('Pagamento pendente'), findsNothing);
  });

  testWidgets('formas de pagar em portugues', (tester) async {
    await tester.pumpWidget(_app(_item(method: 'cash')));
    expect(find.text('Dinheiro'), findsOneWidget);
    await tester.pumpWidget(_app(_item(method: 'balance')));
    expect(find.text('Saldo do app'), findsOneWidget);
  });

  testWidgets('cancelada antes de alguem aceitar nao tem ficha nem total', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(_item(state: RideState.cancelled, rider: null)),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('Cancelada'), findsOneWidget);
    expect(find.text('Total'), findsNothing);
    expect(find.text('Motoqueiro'), findsNothing);
    expect(find.text('Sua nota'), findsNothing);
    expect(find.text('Taxa de cancelamento'), findsNothing);
  });

  testWidgets('cancelada com taxa mostra a taxa; devolvida avisa', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_item(state: RideState.cancelled, fee: 350)));
    expect(find.text('Taxa de cancelamento'), findsOneWidget);
    expect(find.text(brl(350)), findsOneWidget);
    expect(find.text('Total'), findsNothing);

    await tester.pumpWidget(
      _app(_item(state: RideState.cancelled, fee: 350, refunded: true)),
    );
    expect(find.text('${brl(350)} (devolvida)'), findsOneWidget);
  });

  testWidgets('sem moto tambem nao mostra total', (tester) async {
    await tester.pumpWidget(_app(_item(state: RideState.noRider, rider: null)));

    expect(find.text('Sem moto'), findsOneWidget);
    expect(find.text('Total'), findsNothing);
  });

  testWidgets('pagamento pendente aparece na corrida em dinheiro', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_item(method: 'cash', pending: true)));

    expect(find.text('Pagamento pendente'), findsOneWidget);
  });

  testWidgets('endereco de 200 letras nao estoura a tela', (tester) async {
    final longo = 'Rua ${'muito ' * 33}longa';
    await tester.pumpWidget(_app(_item(pickup: longo, destination: longo)));

    expect(tester.takeException(), isNull);
  });
}
