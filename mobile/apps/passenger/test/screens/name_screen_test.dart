import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/name_screen.dart';

Widget _app({Future<void> Function(String)? onSave, VoidCallback? onSignOut}) =>
    MaterialApp(
      home: NameScreen(
        onSave: onSave ?? (_) async {},
        onSignOut: onSignOut ?? () {},
      ),
    );

const _erroDeTamanho = 'Digite seu nome (de 2 a 120 letras).';

void main() {
  testWidgets('nome valido chama onSave sem os espacos das pontas', (
    tester,
  ) async {
    String? recebido;
    await tester.pumpWidget(_app(onSave: (nome) async => recebido = nome));

    expect(find.text('Como podemos te chamar?'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('nome')), '  Ana Lima  ');
    await tester.tap(find.text('Continuar'));
    await tester.pumpAndSettle();

    expect(recebido, 'Ana Lima');
  });

  testWidgets('so espacos ou uma letra mostram o erro e nao chamam onSave', (
    tester,
  ) async {
    var chamadas = 0;
    await tester.pumpWidget(_app(onSave: (_) async => chamadas++));

    for (final texto in ['   ', 'A', '']) {
      await tester.enterText(find.byKey(const Key('nome')), texto);
      await tester.tap(find.text('Continuar'));
      await tester.pumpAndSettle();
      expect(find.text(_erroDeTamanho), findsOneWidget, reason: '"$texto"');
    }
    expect(chamadas, 0);
  });

  testWidgets('121 letras tambem sao recusadas na propria tela', (
    tester,
  ) async {
    var chamadas = 0;
    await tester.pumpWidget(_app(onSave: (_) async => chamadas++));

    await tester.enterText(find.byKey(const Key('nome')), 'a' * 121);
    await tester.tap(find.text('Continuar'));
    await tester.pumpAndSettle();

    expect(find.text(_erroDeTamanho), findsOneWidget);
    expect(chamadas, 0);
  });

  testWidgets('erro do servidor aparece e a tela continua', (tester) async {
    await tester.pumpWidget(
      _app(
        onSave: (_) async => throw ApiException(
          status: 422,
          code: 'invalid',
          message: 'Digite seu nome (de 2 a 120 letras).',
        ),
      ),
    );

    await tester.enterText(find.byKey(const Key('nome')), 'Ana Lima');
    await tester.tap(find.text('Continuar'));
    await tester.pumpAndSettle();

    expect(find.byType(SnackBar), findsOneWidget);
    expect(find.byKey(const Key('nome')), findsOneWidget);
  });

  testWidgets('sem internet mostra a frase da rede', (tester) async {
    await tester.pumpWidget(
      _app(onSave: (_) async => throw NetworkException()),
    );

    await tester.enterText(find.byKey(const Key('nome')), 'Ana Lima');
    await tester.tap(find.text('Continuar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Sem conexão com o servidor. Tente de novo.'),
      findsOneWidget,
    );
  });

  testWidgets('Sair chama onSignOut', (tester) async {
    var saiu = false;
    await tester.pumpWidget(_app(onSignOut: () => saiu = true));

    await tester.tap(find.text('Sair'));

    expect(saiu, isTrue);
  });
}
