import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/wallet_screen.dart';

Widget _app(WalletScreen screen) => MaterialApp(home: screen);

WalletScreen _screen({
  required PassengerState state,
  Future<Charge> Function(int)? onTopup,
  Future<Withdrawal> Function(int, String)? onWithdraw,
  Future<void> Function(String, String)? onSetEmergencyContact,
  Future<void> Function(String, String)? onAppealFee,
  void Function(Charge)? onShowCharge,
}) => WalletScreen(
  state: state,
  onTopup: onTopup ?? (_) async => const Charge(chargeId: 'c', amountCents: 0),
  onWithdraw:
      onWithdraw ??
      (_, _) async => const Withdrawal(
        withdrawalId: 'w1',
        amountCents: 0,
        balanceCents: 0,
        key: 'final 0000',
      ),
  onSetEmergencyContact: onSetEmergencyContact ?? (_, _) async {},
  onAppealFee: onAppealFee ?? (_, _) async {},
  onShowCharge: onShowCharge ?? (_) {},
);

void main() {
  testWidgets('recarga desligada nao mostra o botao', (tester) async {
    await tester.pumpWidget(
      _app(_screen(state: const PassengerState(topupEnabled: false))),
    );

    expect(find.text('Recarregar'), findsNothing);
  });

  testWidgets('recarga ligada chama onTopup e mostra o pix', (tester) async {
    int? centavosRecebidos;
    Charge? mostrado;
    final charge = const Charge(chargeId: 'c1', amountCents: 2000);
    await tester.pumpWidget(
      _app(
        _screen(
          state: const PassengerState(topupEnabled: true),
          onTopup: (cents) async {
            centavosRecebidos = cents;
            return charge;
          },
          onShowCharge: (c) => mostrado = c,
        ),
      ),
    );

    await tester.tap(find.text('Recarregar'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('valor_recarga')), '20');
    await tester.tap(find.text('Confirmar'));
    await tester.pumpAndSettle();

    expect(centavosRecebidos, 2000);
    expect(mostrado, charge);
  });

  testWidgets('saque desligado nao mostra o botao', (tester) async {
    await tester.pumpWidget(
      _app(_screen(state: const PassengerState(withdrawEnabled: false))),
    );

    expect(find.text('Sacar'), findsNothing);
  });

  testWidgets('saque chama onWithdraw com valor e chave', (tester) async {
    int? centavosRecebidos;
    String? chaveRecebida;
    await tester.pumpWidget(
      _app(
        _screen(
          state: const PassengerState(withdrawEnabled: true),
          onWithdraw: (cents, key) async {
            centavosRecebidos = cents;
            chaveRecebida = key;
            return const Withdrawal(
              withdrawalId: 'w1',
              amountCents: 1000,
              balanceCents: 500,
              key: 'final 4725',
            );
          },
        ),
      ),
    );

    await tester.tap(find.text('Sacar'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('valor_saque')), '10');
    await tester.enterText(find.byKey(const Key('chave_pix')), '52998224725');
    await tester.tap(find.text('Confirmar'));
    await tester.pumpAndSettle();

    expect(centavosRecebidos, 1000);
    expect(chaveRecebida, '52998224725');
  });

  testWidgets('salvar contato de emergencia chama onSetEmergencyContact', (
    tester,
  ) async {
    String? nomeRecebido;
    String? telefoneRecebido;
    await tester.pumpWidget(
      _app(
        _screen(
          state: const PassengerState(),
          onSetEmergencyContact: (name, phone) async {
            nomeRecebido = name;
            telefoneRecebido = phone;
          },
        ),
      ),
    );

    await tester.enterText(find.byKey(const Key('contato_nome')), 'Maria');
    await tester.enterText(
      find.byKey(const Key('contato_telefone')),
      '75999990000',
    );
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(nomeRecebido, 'Maria');
    expect(telefoneRecebido, '75999990000');
  });

  testWidgets(
    'taxa recente com recurso permitido mostra o botao e chama onAppealFee com o texto',
    (tester) async {
      String? rideIdRecebido;
      String? textoRecebido;
      await tester.pumpWidget(
        _app(
          _screen(
            state: const PassengerState(
              recentFees: [
                RecentFee(
                  rideId: 'r1',
                  feeCents: 300,
                  createdAt: 1000,
                  fromBalanceCents: 0,
                  retainedCents: 300,
                  pendingCents: 0,
                  appealState: 'none',
                  canAppeal: true,
                ),
              ],
            ),
            onAppealFee: (rideId, texto) async {
              rideIdRecebido = rideId;
              textoRecebido = texto;
            },
          ),
        ),
      );

      await tester.tap(find.text('Pedir recurso'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('texto_recurso')),
        'Não concordo com a taxa.',
      );
      await tester.tap(find.text('Enviar'));
      await tester.pumpAndSettle();

      expect(rideIdRecebido, 'r1');
      expect(textoRecebido, 'Não concordo com a taxa.');
    },
  );

  testWidgets('taxa recente sem recurso permitido nao mostra o botao', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        _screen(
          state: const PassengerState(
            recentFees: [
              RecentFee(
                rideId: 'r1',
                feeCents: 300,
                createdAt: 1000,
                fromBalanceCents: 0,
                retainedCents: 300,
                pendingCents: 0,
                appealState: 'open',
                canAppeal: false,
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.text('Pedir recurso'), findsNothing);
  });

  testWidgets('erro ao sacar mostra a mensagem', (tester) async {
    await tester.pumpWidget(
      _app(
        _screen(
          state: const PassengerState(withdrawEnabled: true),
          onWithdraw: (_, _) async => throw ApiException(
            status: 422,
            code: 'invalid',
            message: 'Chave Pix inválida.',
          ),
        ),
      ),
    );

    await tester.tap(find.text('Sacar'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('valor_saque')), '10');
    await tester.enterText(find.byKey(const Key('chave_pix')), 'xx');
    await tester.tap(find.text('Confirmar'));
    await tester.pumpAndSettle();

    expect(find.text('Chave Pix inválida.'), findsOneWidget);
  });
}
