import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/offer_card.dart';

var _agora = DateTime.fromMillisecondsSinceEpoch(1000000 * 1000);

double get _agoraSegundos => _agora.millisecondsSinceEpoch / 1000;

Offer _oferta({
  String rideId = 'r1',
  double segundosParaVencer = 10,
  String pagamento = 'cash',
  bool fila = false,
  int? segundosAteOPassageiro = 130,
}) => Offer(
  rideId: rideId,
  priceCents: 700,
  paymentMethod: pagamento,
  pickup: const Place(lat: 0, lng: 0, text: 'Rua A, 10'),
  destination: const Place(lat: 0, lng: 0, text: 'Rua B, 20'),
  distanceM: 2300,
  secondsToPickup: segundosAteOPassageiro,
  willQueue: fila,
  expiresAt: _agoraSegundos + segundosParaVencer,
);

Widget _app(
  Offer oferta, {
  Future<void> Function()? onAccept,
  Future<void> Function()? onDecline,
}) => MaterialApp(
  home: Scaffold(
    body: OfferCard(
      offer: oferta,
      onAccept: onAccept ?? () async {},
      onDecline: onDecline ?? () async {},
      clock: () => _agora,
    ),
  ),
);

void main() {
  setUp(() => _agora = DateTime.fromMillisecondsSinceEpoch(1000000 * 1000));

  testWidgets('mostra valor, pagamento, distancia, chegada e enderecos', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_oferta()));

    expect(find.text('R\$ 7,00'), findsOneWidget);
    expect(find.text('Dinheiro'), findsOneWidget);
    expect(find.textContaining('2,3 km'), findsOneWidget);
    expect(find.text('3 min até o passageiro'), findsOneWidget);
    expect(find.textContaining('Rua A, 10'), findsOneWidget);
    expect(find.textContaining('Rua B, 20'), findsOneWidget);
    expect(find.textContaining('espera na fila'), findsNothing);
  });

  testWidgets('pix aparece como Pix e a fila avisa', (tester) async {
    await tester.pumpWidget(
      _app(_oferta(pagamento: 'pix', fila: true, segundosAteOPassageiro: null)),
    );

    expect(find.text('Pix'), findsOneWidget);
    expect(find.textContaining('min até o passageiro'), findsNothing);
    expect(
      find.text(
        'Esta corrida espera na fila: você termina a de agora primeiro.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('o contador desce e para em Tempo esgotado', (tester) async {
    await tester.pumpWidget(_app(_oferta()));
    expect(find.text('Responda em 10s'), findsOneWidget);

    _agora = _agora.add(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Responda em 9s'), findsOneWidget);

    _agora = _agora.add(const Duration(seconds: 30));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Tempo esgotado'), findsOneWidget);
    // quem decide se venceu é o servidor: os botões continuam ligados
    expect(
      tester
          .widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Aceitar'),
          )
          .onPressed,
      isNotNull,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Recusar'),
          )
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('aceitar chama onAccept uma vez mesmo com dois toques', (
    tester,
  ) async {
    var chamadas = 0;
    final pronto = Completer<void>();
    await tester.pumpWidget(
      _app(
        _oferta(),
        onAccept: () {
          chamadas++;
          return pronto.future;
        },
      ),
    );

    await tester.tap(find.text('Aceitar'));
    await tester.pump();
    await tester.tap(find.text('Aceitar'), warnIfMissed: false);
    await tester.pump();

    expect(chamadas, 1);
    pronto.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('recusar chama onDecline', (tester) async {
    var recusou = false;
    await tester.pumpWidget(
      _app(_oferta(), onDecline: () async => recusou = true),
    );

    await tester.tap(find.text('Recusar'));
    await tester.pumpAndSettle();

    expect(recusou, isTrue);
  });

  testWidgets('erro do onAccept mostra a frase e religa os botoes', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        _oferta(),
        onAccept: () async => throw ApiException(
          status: 409,
          code: 'offer_gone',
          message: 'Essa oferta não está mais disponível.',
        ),
      ),
    );

    await tester.tap(find.text('Aceitar'));
    await tester.pumpAndSettle();

    expect(find.text('Essa oferta não está mais disponível.'), findsOneWidget);
    expect(
      tester
          .widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Aceitar'),
          )
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('outra oferta no lugar reinicia o contador e liga os botoes', (
    tester,
  ) async {
    final pronto = Completer<void>();
    await tester.pumpWidget(_app(_oferta(), onAccept: () => pronto.future));
    await tester.tap(find.text('Aceitar'));
    await tester.pump();
    expect(
      tester
          .widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Aceitar'),
          )
          .onPressed,
      isNull,
    );

    await tester.pumpWidget(
      _app(
        _oferta(rideId: 'r2', segundosParaVencer: 20),
        onAccept: () async {},
      ),
    );
    await tester.pump();

    expect(find.text('Responda em 20s'), findsOneWidget);
    expect(
      tester
          .widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Aceitar'),
          )
          .onPressed,
      isNotNull,
    );
    pronto.complete();
    await tester.pumpAndSettle();
  });
}
