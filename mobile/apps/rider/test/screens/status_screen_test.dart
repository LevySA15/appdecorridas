import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/status_screen.dart';

Future<void> _pump(
  WidgetTester tester,
  RiderRegistration registration, {
  Future<void> Function()? onRefresh,
}) => tester.pumpWidget(
  MaterialApp(
    home: StatusScreen(
      registration: registration,
      onRefresh: onRefresh ?? () async {},
      onSignOut: () {},
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

  testWidgets('recusado mostra o motivo e manda falar com o suporte', (
    tester,
  ) async {
    await _pump(
      tester,
      const RiderRegistration(
        status: RegistrationStatus.rejected,
        reason: 'Foto da CNH ilegível.',
      ),
    );
    expect(find.text('Cadastro recusado'), findsOneWidget);
    expect(find.text('Foto da CNH ilegível.'), findsOneWidget);
    expect(find.text('Fale com o suporte.'), findsOneWidget);
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
}
