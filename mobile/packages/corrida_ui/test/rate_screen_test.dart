import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corrida_ui/corrida_ui.dart';

void main() {
  testWidgets('tocar a 4a estrela chama onRate(4)', (tester) async {
    int? estrelasRecebidas;
    await tester.pumpWidget(
      MaterialApp(
        home: RateScreen(
          onRate: (stars) async => estrelasRecebidas = stars,
          onSkip: () {},
        ),
      ),
    );

    await tester.tap(find.byIcon(Icons.star).at(3));
    await tester.pumpAndSettle();

    expect(estrelasRecebidas, 4);
  });

  testWidgets('tocar agora nao chama onSkip', (tester) async {
    var pulado = false;
    await tester.pumpWidget(
      MaterialApp(
        home: RateScreen(onRate: (_) async {}, onSkip: () => pulado = true),
      ),
    );

    await tester.tap(find.text('Agora não'));

    expect(pulado, isTrue);
  });

  testWidgets('erro do onRate mostra a mensagem e continua na tela', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RateScreen(
          onRate: (_) async => throw ApiException(
            status: 409,
            code: 'already_rated',
            message: 'Essa corrida já foi avaliada.',
          ),
          onSkip: () {},
        ),
      ),
    );

    await tester.tap(find.byIcon(Icons.star).first);
    await tester.pumpAndSettle();

    expect(find.text('Essa corrida já foi avaliada.'), findsOneWidget);
    expect(find.byType(RateScreen), findsOneWidget);
  });
}
