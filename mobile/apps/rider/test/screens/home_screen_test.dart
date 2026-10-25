import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/home_screen.dart';
import 'package:rider/screens/offer_card.dart';

final _hoje = DateTime(2026, 10, 25);

RiderAccount _conta({
  int completed = 3,
  bool entryPaid = false,
  String? blockedReason,
  int debt = 0,
  int debtToPay = 0,
}) => RiderAccount(
  completedRides: completed,
  trialRides: 10,
  entryPaid: entryPaid,
  entryFeeCents: 5000,
  needsEntry: blockedReason == 'entry_pending',
  blockedReason: blockedReason,
  cashDebtCents: debt,
  cashDebtLimitCents: 70,
  debtToPayCents: debtToPay,
);

RiderState _estado({
  bool online = false,
  RiderAccount? account,
  Offer? offer,
  RiderRide? ride,
  RiderRide? queued,
  RiderRide? awaiting,
  DateTime? cnh,
  DateTime? crlv,
  double? rating,
  int ratingCount = 0,
}) => RiderState(
  registration: RiderRegistration(
    status: RegistrationStatus.approved,
    online: online,
    cnhExpiresOn: cnh ?? DateTime(2030, 1, 1),
    crlvExpiresOn: crlv ?? DateTime(2030, 1, 1),
    rating: rating,
    ratingCount: ratingCount,
  ),
  account: account ?? _conta(),
  offer: offer,
  ride: ride,
  queuedRide: queued,
  awaitingPayment: awaiting,
);

const _oferta = Offer(rideId: 'r1', priceCents: 700, paymentMethod: 'pix');
const _corrida = RiderRide(
  rideId: 'r1',
  state: RideState.accepted,
  passengerName: 'Ana',
  priceCents: 700,
);

Future<void> _pump(
  WidgetTester tester,
  RiderState state, {
  Future<void> Function()? onGoOnline,
  Future<void> Function()? onGoOffline,
  Future<void> Function(String)? onAcceptOffer,
  VoidCallback? onOpenRide,
  Future<Charge> Function()? onPayEntry,
  Future<Charge> Function()? onPayDebt,
  Future<Charge> Function(String)? onLoadCharge,
  void Function(Charge)? onShowCharge,
  Future<void> Function(String)? onCashReceived,
  VoidCallback? onRenewDocuments,
}) async {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      home: HomeScreen(
        state: state,
        onGoOnline: onGoOnline ?? () async {},
        onGoOffline: onGoOffline ?? () async {},
        onAcceptOffer: onAcceptOffer ?? (_) async {},
        onDeclineOffer: (_) async {},
        onOpenRide: onOpenRide ?? () {},
        onPayEntry:
            onPayEntry ??
            () async => const Charge(chargeId: 'e1', amountCents: 5000),
        onPayDebt:
            onPayDebt ??
            () async => const Charge(chargeId: 'd1', amountCents: 70),
        onLoadCharge:
            onLoadCharge ??
            (id) async => Charge(chargeId: id, amountCents: 700),
        onShowCharge: onShowCharge ?? (_) {},
        onCashReceived: onCashReceived ?? (_) async {},
        onRenewDocuments: onRenewDocuments ?? () {},
        onSignOut: () {},
        clock: () => _hoje,
      ),
    ),
  );
}

void main() {
  testWidgets('ligar o interruptor chama onGoOnline', (tester) async {
    var ligou = false;
    await _pump(tester, _estado(), onGoOnline: () async => ligou = true);

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    expect(ligou, isTrue);
  });

  testWidgets('desligar o interruptor chama onGoOffline', (tester) async {
    var desligou = false;
    await _pump(
      tester,
      _estado(online: true),
      onGoOffline: () async => desligou = true,
    );

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    expect(desligou, isTrue);
  });

  testWidgets('erro ao ficar disponivel mostra a frase do servidor', (
    tester,
  ) async {
    await _pump(
      tester,
      _estado(),
      onGoOnline: () async => throw ApiException(
        status: 409,
        code: 'not_approved',
        message: 'Seu cadastro ainda não foi aprovado.',
      ),
    );

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    expect(find.text('Seu cadastro ainda não foi aprovado.'), findsOneWidget);
  });

  testWidgets('entrada pendente mostra a faixa e abre o Pix', (tester) async {
    Charge? mostrada;
    await _pump(
      tester,
      _estado(account: _conta(completed: 10, blockedReason: 'entry_pending')),
      onShowCharge: (c) => mostrada = c,
    );

    expect(
      find.text(
        'Você fez as 10 corridas de teste. Pague a entrada de R\$ 50,00 para continuar.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('Pagar entrada'));
    await tester.pumpAndSettle();

    expect(mostrada?.chargeId, 'e1');
  });

  testWidgets('divida pendente mostra a taxa e abre o Pix', (tester) async {
    Charge? mostrada;
    await _pump(
      tester,
      _estado(
        account: _conta(blockedReason: 'debt_pending', debt: 70, debtToPay: 70),
      ),
      onShowCharge: (c) => mostrada = c,
    );

    expect(find.text('Taxa a pagar: R\$ 0,70'), findsOneWidget);
    await tester.tap(find.text('Pagar taxa'));
    await tester.pumpAndSettle();

    expect(mostrada?.chargeId, 'd1');
  });

  testWidgets('documento vencendo em 10 dias avisa e leva a renovar', (
    tester,
  ) async {
    var renovou = false;
    await _pump(
      tester,
      _estado(cnh: DateTime(2026, 11, 4)),
      onRenewDocuments: () => renovou = true,
    );

    expect(find.text('A CNH vence em 04/11/2026'), findsOneWidget);
    await tester.tap(find.text('Enviar novo'));
    expect(renovou, isTrue);
  });

  testWidgets('documento vencido diz que venceu', (tester) async {
    await _pump(tester, _estado(crlv: DateTime(2026, 10, 1)));

    expect(
      find.text('O documento da moto venceu em 01/10/2026'),
      findsOneWidget,
    );
  });

  testWidgets('documentos longe de vencer nao avisam', (tester) async {
    await _pump(tester, _estado(cnh: DateTime(2027, 1, 1)));

    expect(find.text('Enviar novo'), findsNothing);
  });

  testWidgets('oferta aparece e aceitar manda o ride_id', (tester) async {
    String? aceita;
    await _pump(
      tester,
      _estado(online: true, offer: _oferta),
      onAcceptOffer: (id) async => aceita = id,
    );

    expect(find.byType(OfferCard), findsOneWidget);
    await tester.tap(find.text('Aceitar'));
    await tester.pumpAndSettle();

    expect(aceita, 'r1');
  });

  testWidgets('corrida em andamento tem botao de abrir', (tester) async {
    var abriu = false;
    await _pump(
      tester,
      _estado(ride: _corrida),
      onOpenRide: () => abriu = true,
    );

    expect(find.text('Corrida em andamento'), findsOneWidget);
    await tester.tap(find.text('Abrir corrida'));
    expect(abriu, isTrue);
  });

  testWidgets('corrida na fila aparece so como aviso', (tester) async {
    await _pump(
      tester,
      _estado(
        queued: const RiderRide(
          rideId: 'r2',
          state: RideState.queued,
          passengerName: 'Bia',
        ),
      ),
    );

    expect(find.text('Próxima na fila: Bia'), findsOneWidget);
  });

  testWidgets('cobranca em dinheiro: ver Pix e recebi o dinheiro', (
    tester,
  ) async {
    String? carregada;
    Charge? mostrada;
    String? recebida;
    await _pump(
      tester,
      _estado(
        awaiting: const RiderRide(
          rideId: 'r1',
          state: RideState.completed,
          priceCents: 700,
          endPayment: EndPayment(chargeId: 'c9', amountCents: 700),
        ),
      ),
      onLoadCharge: (id) async {
        carregada = id;
        return Charge(chargeId: id, amountCents: 700);
      },
      onShowCharge: (c) => mostrada = c,
      onCashReceived: (id) async => recebida = id,
    );

    expect(find.text('Cobrar R\$ 7,00 em dinheiro'), findsOneWidget);
    await tester.tap(find.text('Ver Pix'));
    await tester.pumpAndSettle();
    expect(carregada, 'c9');
    expect(mostrada?.chargeId, 'c9');

    await tester.tap(find.text('Recebi o dinheiro'));
    await tester.pumpAndSettle();
    expect(recebida, 'r1');
  });

  testWidgets('cobranca sem QR nao mostra Ver Pix; bloqueado explica', (
    tester,
  ) async {
    await _pump(
      tester,
      _estado(
        awaiting: const RiderRide(
          rideId: 'r1',
          state: RideState.completed,
          priceCents: 700,
          endPayment: EndPayment(amountCents: 700, blocked: true),
        ),
      ),
    );

    expect(find.text('Ver Pix'), findsNothing);
    expect(
      find.text(
        'O passageiro foi bloqueado até pagar; você recebe quando ele pagar.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('resumo mostra teste, avaliacao e taxas devidas', (tester) async {
    await _pump(
      tester,
      _estado(
        account: _conta(completed: 3, debt: 70),
        rating: 4.8,
        ratingCount: 12,
      ),
    );

    expect(find.text('Corridas de teste: 3 de 10'), findsOneWidget);
    expect(find.text('4,8 (12 avaliações)'), findsOneWidget);
    expect(find.text('Taxas devidas: R\$ 0,70'), findsOneWidget);
  });
}
