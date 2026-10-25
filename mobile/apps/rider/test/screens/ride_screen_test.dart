import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/offer_card.dart';
import 'package:rider/screens/ride_screen.dart';

const _embarque = Place(lat: -12.96, lng: -39.26, text: 'Rua A, 10');
const _destino = Place(lat: -12.97, lng: -39.25, text: 'Rua B, 20');

RiderRide _corrida({
  RideState state = RideState.accepted,
  String method = 'cash',
  bool pixPaid = false,
  bool helmet = false,
}) => RiderRide(
  rideId: 'r1',
  state: state,
  priceCents: 700,
  method: method,
  pixPaid: pixPaid,
  helmetConfirmed: helmet,
  passengerName: 'Ana',
  pickup: _embarque,
  destination: _destino,
);

Future<void> _pump(
  WidgetTester tester,
  RiderRide ride, {
  Offer? offer,
  void Function(Place)? onMove,
  Future<void> Function()? onArrive,
  Future<void> Function()? onConfirmHelmet,
  Future<void> Function(String)? onStart,
  Future<void> Function()? onComplete,
  Future<void> Function(String)? onAcceptOffer,
}) async {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      home: RideScreen(
        ride: ride,
        position: cityCenter,
        offer: offer,
        onMove: onMove ?? (_) {},
        onArrive: onArrive ?? () async {},
        onConfirmHelmet: onConfirmHelmet ?? () async {},
        onStart: onStart ?? (_) async {},
        onComplete: onComplete ?? () async {},
        onAcceptOffer: onAcceptOffer ?? (_) async {},
        onDeclineOffer: (_) async {},
      ),
    ),
  );
}

ElevatedButton _botao(WidgetTester tester, String texto) =>
    tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, texto));

String _codigoDigitado(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(const Key('codigo'))).controller!.text;

void main() {
  testWidgets('aceita: mostra o embarque e Cheguei chama onArrive', (
    tester,
  ) async {
    var chegou = false;
    await _pump(tester, _corrida(), onArrive: () async => chegou = true);

    expect(find.text('Vá buscar Ana'), findsOneWidget);
    expect(find.text('Embarque: Rua A, 10'), findsOneWidget);
    await tester.tap(find.text('Cheguei'));
    await tester.pumpAndSettle();

    expect(chegou, isTrue);
  });

  testWidgets('ir ate o ponto de embarque manda o pickup para onMove', (
    tester,
  ) async {
    Place? movido;
    await _pump(tester, _corrida(), onMove: (p) => movido = p);

    await tester.tap(find.text('Ir até o ponto de embarque'));

    expect(movido?.lat, _embarque.lat);
    expect(movido?.lng, _embarque.lng);
  });

  testWidgets('tocar no mapa manda um ponto para onMove', (tester) async {
    Place? movido;
    await _pump(tester, _corrida(), onMove: (p) => movido = p);

    await tester.tapAt(tester.getCenter(find.byType(FakeMapView)));

    expect(movido, isNotNull);
    expect((movido!.lat - cityCenter.lat).abs(), lessThan(1e-3));
  });

  testWidgets('chegou sem capacete: comecar fica desligado com 4 digitos', (
    tester,
  ) async {
    await _pump(tester, _corrida(state: RideState.arrived));
    await tester.enterText(find.byKey(const Key('codigo')), '1234');
    await tester.pump();

    expect(
      find.text('Peça o código de 4 dígitos ao passageiro'),
      findsOneWidget,
    );
    expect(_botao(tester, 'Começar corrida').onPressed, isNull);
  });

  testWidgets('capacete ok, dinheiro e 4 digitos: comecar manda o codigo', (
    tester,
  ) async {
    String? codigo;
    await _pump(
      tester,
      _corrida(state: RideState.arrived, helmet: true),
      onStart: (pin) async => codigo = pin,
    );
    await tester.enterText(find.byKey(const Key('codigo')), '1234');
    await tester.pump();

    expect(find.text('Capacete confirmado'), findsOneWidget);
    await tester.tap(find.text('Começar corrida'));
    await tester.pumpAndSettle();

    expect(codigo, '1234');
  });

  testWidgets('pix nao pago mostra a espera e desliga o comecar', (
    tester,
  ) async {
    await _pump(
      tester,
      _corrida(state: RideState.arrived, method: 'pix', helmet: true),
    );
    await tester.enterText(find.byKey(const Key('codigo')), '1234');
    await tester.pump();

    expect(find.text('Aguardando o Pix do passageiro…'), findsOneWidget);
    expect(_botao(tester, 'Começar corrida').onPressed, isNull);
  });

  testWidgets('pix pago libera o comecar', (tester) async {
    await _pump(
      tester,
      _corrida(
        state: RideState.arrived,
        method: 'pix',
        pixPaid: true,
        helmet: true,
      ),
    );
    await tester.enterText(find.byKey(const Key('codigo')), '1234');
    await tester.pump();

    expect(find.textContaining('Aguardando o Pix'), findsNothing);
    expect(_botao(tester, 'Começar corrida').onPressed, isNotNull);
  });

  testWidgets('corrida em dinheiro nao espera pix', (tester) async {
    await _pump(tester, _corrida(state: RideState.arrived, helmet: true));

    expect(find.textContaining('Aguardando o Pix'), findsNothing);
  });

  testWidgets('o campo do codigo aceita so digitos e no maximo 4', (
    tester,
  ) async {
    await _pump(tester, _corrida(state: RideState.arrived, helmet: true));

    await tester.enterText(find.byKey(const Key('codigo')), 'a1b2c3d4e5');
    await tester.pump();

    expect(_codigoDigitado(tester), '1234');
  });

  testWidgets('wrong_pin mostra a mensagem e limpa o campo', (tester) async {
    await _pump(
      tester,
      _corrida(state: RideState.arrived, helmet: true),
      onStart: (_) async => throw ApiException(
        status: 422,
        code: 'wrong_pin',
        message: 'Código errado.',
      ),
    );
    await tester.enterText(find.byKey(const Key('codigo')), '0000');
    await tester.pump();

    await tester.tap(find.text('Começar corrida'));
    await tester.pumpAndSettle();

    expect(find.text('Código errado.'), findsOneWidget);
    expect(_codigoDigitado(tester), '');
  });

  testWidgets('429 do codigo mostra a mensagem e mantem a tela', (
    tester,
  ) async {
    await _pump(
      tester,
      _corrida(state: RideState.arrived, helmet: true),
      onStart: (_) async => throw ApiException(
        status: 429,
        code: 'too_many_requests',
        message: 'Muitos códigos errados. Espere alguns minutos.',
      ),
    );
    await tester.enterText(find.byKey(const Key('codigo')), '1111');
    await tester.pump();

    await tester.tap(find.text('Começar corrida'));
    await tester.pumpAndSettle();

    expect(
      find.text('Muitos códigos errados. Espere alguns minutos.'),
      findsOneWidget,
    );
    expect(find.byType(RideScreen), findsOneWidget);
  });

  testWidgets('confirmar o capacete chama onConfirmHelmet uma vez', (
    tester,
  ) async {
    var chamadas = 0;
    final pronto = Completer<void>();
    await _pump(
      tester,
      _corrida(state: RideState.arrived),
      onConfirmHelmet: () {
        chamadas++;
        return pronto.future;
      },
    );

    await tester.tap(find.text('Confirmei o capacete extra'));
    await tester.pump();
    await tester.tap(
      find.text('Confirmei o capacete extra'),
      warnIfMissed: false,
    );
    await tester.pump();

    expect(chamadas, 1);
    pronto.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('em viagem: finalizar chama onComplete uma vez', (tester) async {
    var chamadas = 0;
    final pronto = Completer<void>();
    await _pump(
      tester,
      _corrida(state: RideState.inProgress),
      onComplete: () {
        chamadas++;
        return pronto.future;
      },
    );

    expect(find.text('Levando Ana'), findsOneWidget);
    expect(find.text('Destino: Rua B, 20'), findsOneWidget);
    await tester.tap(find.text('Finalizar corrida'));
    await tester.pump();
    await tester.tap(find.text('Finalizar corrida'), warnIfMissed: false);
    await tester.pump();

    expect(chamadas, 1);
    pronto.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('ir ate o destino manda o destination para onMove', (
    tester,
  ) async {
    Place? movido;
    await _pump(
      tester,
      _corrida(state: RideState.inProgress),
      onMove: (p) => movido = p,
    );

    await tester.tap(find.text('Ir até o destino'));

    expect(movido?.lat, _destino.lat);
    expect(movido?.lng, _destino.lng);
  });

  testWidgets('corrida terminada nao desenha nada', (tester) async {
    await _pump(tester, _corrida(state: RideState.completed));

    expect(find.byType(FakeMapView), findsNothing);
    expect(find.text('Finalizar corrida'), findsNothing);
  });

  testWidgets('oferta durante a corrida aparece e aceitar manda o ride_id', (
    tester,
  ) async {
    String? aceita;
    await _pump(
      tester,
      _corrida(state: RideState.inProgress),
      offer: const Offer(
        rideId: 'r2',
        priceCents: 500,
        paymentMethod: 'pix',
        willQueue: true,
      ),
      onAcceptOffer: (id) async => aceita = id,
    );

    expect(find.byType(OfferCard), findsOneWidget);
    await tester.tap(find.text('Aceitar'));
    await tester.pumpAndSettle();

    expect(aceita, 'r2');
  });
}
