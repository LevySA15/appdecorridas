import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:passenger/screens/request_ride_screen.dart';

Quote _quote({List<String> paymentMethods = const ['pix', 'cash', 'balance']}) =>
    Quote(
      quoteId: 'q1',
      priceCents: 1200,
      distanceM: 2500,
      durationS: 480,
      reason: 'normal',
      expiresAt: 999999,
      pickup: const Place(lat: -12.96, lng: -39.26),
      destination: const Place(lat: -12.97, lng: -39.27),
      etaSeconds: 180,
      nearbyRiders: 2,
      paymentMethods: paymentMethods,
    );

Future<void> _marcarOsDoisPontos(WidgetTester tester) async {
  final rect = tester.getRect(find.byType(FakeMapPicker));
  await tester.tapAt(rect.topLeft + const Offset(20, 20));
  await tester.pump();
  await tester.tapAt(rect.bottomRight - const Offset(20, 20));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('marcar os dois pontos pede a cotacao e mostra o preco', (
    tester,
  ) async {
    var chamado = false;
    await tester.pumpWidget(
      MaterialApp(
        home: RequestRideScreen(
          onQuote: (pickup, destination) async {
            chamado = true;
            return _quote();
          },
          onConfirm: (_, _) async {},
        ),
      ),
    );

    await _marcarOsDoisPontos(tester);

    expect(chamado, isTrue);
    expect(find.text('R\$ 12,00'), findsOneWidget);
  });

  testWidgets('escolher pagamento e confirmar chama onConfirm com o metodo certo', (
    tester,
  ) async {
    String? quoteIdRecebido;
    String? metodoRecebido;
    await tester.pumpWidget(
      MaterialApp(
        home: RequestRideScreen(
          onQuote: (_, _) async => _quote(),
          onConfirm: (quoteId, method) async {
            quoteIdRecebido = quoteId;
            metodoRecebido = method;
          },
        ),
      ),
    );

    await _marcarOsDoisPontos(tester);

    await tester.tap(find.text('Dinheiro'));
    await tester.pump();
    await tester.tap(find.text('Pedir corrida'));
    await tester.pumpAndSettle();

    expect(quoteIdRecebido, 'q1');
    expect(metodoRecebido, 'cash');
  });

  testWidgets('cotacao so oferece saldo quando o quote permite', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RequestRideScreen(
          onQuote: (_, _) async => _quote(paymentMethods: const ['pix', 'cash']),
          onConfirm: (_, _) async {},
        ),
      ),
    );

    await _marcarOsDoisPontos(tester);

    expect(find.text('Saldo'), findsNothing);
  });

  testWidgets('cotacao vencida ao confirmar volta a marcar', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RequestRideScreen(
          onQuote: (_, _) async => _quote(),
          onConfirm: (_, _) async => throw ApiException(
            status: 409,
            code: 'quote_expired',
            message: 'A cotação venceu.',
          ),
        ),
      ),
    );

    await _marcarOsDoisPontos(tester);
    await tester.tap(find.text('Pedir corrida'));
    await tester.pumpAndSettle();

    expect(find.text('Essa cotação venceu, marque de novo.'), findsOneWidget);
    expect(find.text('R\$ 12,00'), findsNothing);
    expect(find.byType(FakeMapPicker), findsOneWidget);
  });

  testWidgets('erro de rede na cotacao mostra mensagem e deixa marcar de novo', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RequestRideScreen(
          onQuote: (_, _) async => throw NetworkException('Sem conexão.'),
          onConfirm: (_, _) async {},
        ),
      ),
    );

    await _marcarOsDoisPontos(tester);

    expect(find.text('Sem conexão.'), findsOneWidget);
    expect(find.byType(FakeMapPicker), findsOneWidget);
  });
}
