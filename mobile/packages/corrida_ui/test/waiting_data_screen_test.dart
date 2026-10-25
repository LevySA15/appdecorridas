import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _app({
  required Future<void> Function() onRetry,
  VoidCallback? onSignOut,
}) => MaterialApp(
  home: WaitingDataScreen(onRetry: onRetry, onSignOut: onSignOut ?? () {}),
);

void main() {
  testWidgets('explica a espera e oferece tentar de novo e sair', (
    tester,
  ) async {
    await tester.pumpWidget(_app(onRetry: () async {}));

    expect(find.text('Carregando seus dados…'), findsOneWidget);
    expect(find.text('Tentar de novo'), findsOneWidget);
    expect(find.text('Sair'), findsOneWidget);
  });

  testWidgets('tentar de novo chama onRetry', (tester) async {
    var tentou = 0;
    await tester.pumpWidget(_app(onRetry: () async => tentou++));

    await tester.tap(find.text('Tentar de novo'));
    await tester.pumpAndSettle();

    expect(tentou, 1);
  });

  testWidgets(
    'erro ao tentar de novo mostra a frase e deixa tentar outra vez',
    (tester) async {
      await tester.pumpWidget(
        _app(onRetry: () async => throw NetworkException('Sem internet.')),
      );

      await tester.tap(find.text('Tentar de novo'));
      await tester.pumpAndSettle();

      expect(find.text('Sem internet.'), findsOneWidget);
      expect(
        tester
            .widget<ElevatedButton>(
              find.widgetWithText(ElevatedButton, 'Tentar de novo'),
            )
            .onPressed,
        isNotNull,
      );
    },
  );

  testWidgets('sair chama onSignOut', (tester) async {
    var saiu = false;
    await tester.pumpWidget(
      _app(onRetry: () async {}, onSignOut: () => saiu = true),
    );

    await tester.tap(find.text('Sair'));

    expect(saiu, isTrue);
  });
}
