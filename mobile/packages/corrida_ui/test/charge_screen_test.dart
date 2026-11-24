import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
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

  testWidgets('avisa que pode fechar a tela depois de pagar', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: ChargeScreen(charge: _charge)),
    );

    // a tela não se atualiza sozinha: quem muda é a tela de trás (pelo estado)
    expect(
      find.text('Depois de pagar, pode fechar esta tela.'),
      findsOneWidget,
    );
    expect(find.textContaining('atualiza sozinha'), findsNothing);
  });

  testWidgets(
    'mostra o QR do codigo e copiar poe o codigo na area de transferencia',
    (tester) async {
      String? copiado;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copiado = (call.arguments as Map)['text'] as String?;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      await tester.pumpWidget(
        const MaterialApp(home: ChargeScreen(charge: _charge)),
      );

      expect(find.byType(QrImageView), findsOneWidget);
      await tester.tap(find.text('Copiar código'));
      await tester.pump();

      expect(copiado, '00020126...');
      expect(find.text('Código copiado.'), findsOneWidget);
    },
  );

  testWidgets('sem codigo nao desenha QR nem botao de copiar', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ChargeScreen(
          charge: Charge(chargeId: 'c3', amountCents: 100, purpose: 'ride'),
        ),
      ),
    );

    expect(find.byType(QrImageView), findsNothing);
    expect(find.text('Copiar código'), findsNothing);
  });

  testWidgets('cabe em celular pequeno com letra grande', (tester) async {
    tester.view.devicePixelRatio = 2;
    tester.view.physicalSize = const Size(640, 1136);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: const TextScaler.linear(1.5)),
          child: child!,
        ),
        home: ChargeScreen(
          charge: const Charge(
            chargeId: 'c4',
            amountCents: 1850,
            brCode: '00020126580014br.gov.bcb.pix0136123e4567-e89b-12d3-a456-4266141740005204000053039865802BR5913Fulano de Tal6008BRASILIA62070503***63041D3D',
            purpose: 'end',
          ),
          onDone: () {},
        ),
      ),
    );

    expect(tester.takeException(), isNull);
  });
}
