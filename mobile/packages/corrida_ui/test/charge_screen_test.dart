import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corrida_ui/corrida_ui.dart';

const _charge = Charge(
  chargeId: 'c1',
  amountCents: 750,
  brCode: '00020126...',
  purpose: 'ride',
);

void main() {
  testWidgets('mostra o valor, o titulo e o codigo do pix', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: ChargeScreen(charge: _charge)),
    );

    expect(find.text('R\$ 7,50'), findsOneWidget);
    expect(find.textContaining('00020126'), findsOneWidget);
    expect(find.text('Pix da corrida'), findsOneWidget);
  });

  testWidgets('sem onDone nao mostra botao de fechar', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: ChargeScreen(charge: _charge)),
    );

    expect(find.byType(ElevatedButton), findsNothing);
  });

  testWidgets('com onDone, tocar o botao chama o callback', (tester) async {
    var chamado = false;
    await tester.pumpWidget(
      MaterialApp(
        home: ChargeScreen(charge: _charge, onDone: () => chamado = true),
      ),
    );

    await tester.tap(find.byType(ElevatedButton));
    await tester.pump();

    expect(chamado, isTrue);
  });

  testWidgets('titulo da entrada e da divida do motoqueiro', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ChargeScreen(
          charge: Charge(chargeId: 'c2', amountCents: 5000, purpose: 'entry'),
        ),
      ),
    );
    expect(find.text('Pix da entrada'), findsOneWidget);

    await tester.pumpWidget(
      const MaterialApp(
        home: ChargeScreen(
          charge: Charge(chargeId: 'c3', amountCents: 70, purpose: 'debt'),
        ),
      ),
    );
    expect(find.text('Pix da dívida'), findsOneWidget);
  });
}
