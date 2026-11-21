import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/profile_screen.dart';

Widget _app({
  PassengerState state = const PassengerState(
    name: 'Ana Lima',
    phone: '+5575999990001',
  ),
  Future<void> Function(String)? onSaveName,
  Future<void> Function(String, String)? onSetEmergencyContact,
  VoidCallback? onSignOut,
}) => MaterialApp(
  home: ProfileScreen(
    state: state,
    onSaveName: onSaveName ?? (_) async {},
    onSetEmergencyContact: onSetEmergencyContact ?? (_, _) async {},
    onSignOut: onSignOut ?? () {},
  ),
);

void main() {
  testWidgets('mostra o telefone e o nome atuais', (tester) async {
    await tester.pumpWidget(_app());

    expect(find.byKey(const Key('perfil_telefone')), findsOneWidget);
    expect(find.text('+5575999990001'), findsOneWidget);
    final campo = tester.widget<TextField>(
      find.byKey(const Key('perfil_nome')),
    );
    expect(campo.controller!.text, 'Ana Lima');
  });

  testWidgets('salvar nome chama onSaveName com o texto sem as pontas', (
    tester,
  ) async {
    String? recebido;
    await tester.pumpWidget(_app(onSaveName: (nome) async => recebido = nome));

    await tester.enterText(find.byKey(const Key('perfil_nome')), ' Ana Souza ');
    await tester.tap(find.text('Salvar nome'));
    await tester.pumpAndSettle();

    expect(recebido, 'Ana Souza');
  });

  testWidgets('nome curto demais nao chama onSaveName', (tester) async {
    var chamadas = 0;
    await tester.pumpWidget(_app(onSaveName: (_) async => chamadas++));

    await tester.enterText(find.byKey(const Key('perfil_nome')), 'A');
    await tester.tap(find.text('Salvar nome'));
    await tester.pumpAndSettle();

    expect(chamadas, 0);
    expect(find.text('Digite seu nome (de 2 a 120 letras).'), findsOneWidget);
  });

  testWidgets('contato de emergencia vem do estado e salva', (tester) async {
    String? nomeRecebido;
    String? telefoneRecebido;
    await tester.pumpWidget(
      _app(
        state: const PassengerState(
          name: 'Ana Lima',
          phone: '+5575999990001',
          emergencyContact: EmergencyContact(
            name: 'Maria',
            phone: '+5575988510824',
          ),
        ),
        onSetEmergencyContact: (name, phone) async {
          nomeRecebido = name;
          telefoneRecebido = phone;
        },
      ),
    );

    final nome = tester.widget<TextField>(
      find.byKey(const Key('contato_nome')),
    );
    expect(nome.controller!.text, 'Maria');
    await tester.enterText(
      find.byKey(const Key('contato_telefone')),
      '75999990000',
    );
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(nomeRecebido, 'Maria');
    expect(telefoneRecebido, '75999990000');
  });

  testWidgets('erro ao salvar o contato aparece numa mensagem', (tester) async {
    await tester.pumpWidget(
      _app(
        onSetEmergencyContact: (_, _) async => throw ApiException(
          status: 422,
          code: 'invalid',
          message: 'Use o número de outra pessoa, que possa te ajudar.',
        ),
      ),
    );

    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Use o número de outra pessoa, que possa te ajudar.'),
      findsOneWidget,
    );
  });

  testWidgets('Sair chama onSignOut', (tester) async {
    var saiu = false;
    await tester.pumpWidget(_app(onSignOut: () => saiu = true));

    await tester.ensureVisible(find.text('Sair'));
    await tester.tap(find.text('Sair'));

    expect(saiu, isTrue);
  });
}
