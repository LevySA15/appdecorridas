import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corrida_ui/corrida_ui.dart';

Widget _app({
  required Future<void> Function(String phone) onRequestCode,
  required Future<void> Function(String phone, String code) onVerify,
}) => MaterialApp(
  home: LoginScreen(onRequestCode: onRequestCode, onVerify: onVerify),
);

void main() {
  testWidgets('digitar telefone e enviar chama onRequestCode', (tester) async {
    String? telefoneRecebido;
    await tester.pumpWidget(
      _app(
        onRequestCode: (phone) async => telefoneRecebido = phone,
        onVerify: (_, _) async {},
      ),
    );

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();

    expect(telefoneRecebido, '75988510824');
    expect(find.byKey(const Key('codigo')), findsOneWidget);
  });

  testWidgets('digitar codigo e entrar chama onVerify com telefone e codigo', (
    tester,
  ) async {
    String? telefoneRecebido;
    String? codigoRecebido;
    await tester.pumpWidget(
      _app(
        onRequestCode: (_) async {},
        onVerify: (phone, code) async {
          telefoneRecebido = phone;
          codigoRecebido = code;
        },
      ),
    );

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('codigo')), '123456');
    await tester.tap(find.text('Entrar'));
    await tester.pumpAndSettle();

    expect(telefoneRecebido, '75988510824');
    expect(codigoRecebido, '123456');
  });

  testWidgets('erro do onRequestCode mostra a mensagem', (tester) async {
    await tester.pumpWidget(
      _app(
        onRequestCode: (_) async => throw ApiException(
          status: 429,
          code: 'too_many_requests',
          message: 'Espere um pouco e tente de novo.',
        ),
        onVerify: (_, _) async {},
      ),
    );

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();

    expect(find.text('Espere um pouco e tente de novo.'), findsOneWidget);
    expect(find.byKey(const Key('codigo')), findsNothing);
  });

  testWidgets('erro do onVerify mostra a mensagem e deixa tentar de novo', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        onRequestCode: (_) async {},
        onVerify: (_, _) async => throw ApiException(
          status: 401,
          code: 'code_invalid',
          message: 'Código errado ou vencido.',
        ),
      ),
    );

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('codigo')), '123456');
    await tester.tap(find.text('Entrar'));
    await tester.pumpAndSettle();

    expect(find.text('Código errado ou vencido.'), findsOneWidget);
    expect(find.byKey(const Key('codigo')), findsOneWidget);
  });
}
