import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/status_screen.dart';

Future<void> _pump(
  WidgetTester tester,
  RiderRegistration registration, {
  Future<void> Function()? onRefresh,
  VoidCallback? onRenewDocuments,
}) => tester.pumpWidget(
  MaterialApp(
    home: StatusScreen(
      registration: registration,
      onRefresh: onRefresh ?? () async {},
      onSignOut: () {},
      onRenewDocuments: onRenewDocuments,
    ),
  ),
);

void main() {
  testWidgets('pendente avisa que esta em analise', (tester) async {
    await _pump(
      tester,
      const RiderRegistration(status: RegistrationStatus.pending),
    );
    expect(
      find.text('Cadastro em análise. Avisamos aqui quando for aprovado.'),
      findsOneWidget,
    );
  });

  testWidgets('bloqueado mostra o motivo', (tester) async {
    await _pump(
      tester,
      const RiderRegistration(
        status: RegistrationStatus.blocked,
        reason: 'Documento vencido.',
      ),
    );
    expect(find.text('Conta bloqueada'), findsOneWidget);
    expect(find.text('Documento vencido.'), findsOneWidget);
  });

  testWidgets('estado desconhecido pede para atualizar', (tester) async {
    await _pump(
      tester,
      const RiderRegistration(status: RegistrationStatus.unknown),
    );
    expect(
      find.text('Não conseguimos ler o seu cadastro. Toque em atualizar.'),
      findsOneWidget,
    );
  });

  testWidgets('atualizar chama onRefresh', (tester) async {
    var chamado = false;
    await _pump(
      tester,
      const RiderRegistration(status: RegistrationStatus.pending),
      onRefresh: () async => chamado = true,
    );
    await tester.tap(find.text('Atualizar'));
    await tester.pumpAndSettle();
    expect(chamado, isTrue);
  });

  testWidgets('erro ao atualizar mostra a mensagem', (tester) async {
    await _pump(
      tester,
      const RiderRegistration(status: RegistrationStatus.pending),
      onRefresh: () async => throw NetworkException('Sem internet.'),
    );
    await tester.tap(find.text('Atualizar'));
    await tester.pumpAndSettle();
    expect(find.text('Sem internet.'), findsOneWidget);
  });

  testWidgets('bloqueado oferece enviar o documento novo', (tester) async {
    var abriu = false;
    await _pump(
      tester,
      const RiderRegistration(
        status: RegistrationStatus.blocked,
        reason: 'documento vencido',
      ),
      onRenewDocuments: () => abriu = true,
    );

    expect(
      find.text(
        'Se o bloqueio foi por documento vencido, envie o documento novo, com a foto, e a conta é liberada na hora.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('Enviar documento novo'));
    expect(abriu, isTrue);
  });

  testWidgets('em analise nao oferece enviar documento', (tester) async {
    await _pump(
      tester,
      const RiderRegistration(status: RegistrationStatus.pending),
      onRenewDocuments: () {},
    );
    expect(find.text('Enviar documento novo'), findsNothing);
  });
}
