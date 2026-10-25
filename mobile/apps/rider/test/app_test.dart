import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rider/app.dart';
import 'package:rider/screens/home_screen.dart';
import 'package:rider/screens/offer_card.dart';
import 'package:rider/screens/registration_screen.dart';
import 'package:rider/screens/renew_documents_screen.dart';
import 'package:rider/screens/ride_screen.dart';
import 'package:rider/screens/status_screen.dart';

import 'support/fakes.dart';
import 'support/mundo.dart';

const _lugar = {'lat': -12.9644, 'lng': -39.2597, 'text': 'Rua A'};

Map<String, Object?> _corrida({
  String id = 'r1',
  String state = 'accepted',
  String method = 'cash',
  Map<String, Object?>? endPayment,
}) => {
  'ride_id': id,
  'state': state,
  'price_cents': 700,
  'method': method,
  'passenger': {'name': 'Ana'},
  'pickup': _lugar,
  'destination': _lugar,
  'end_payment': endPayment,
};

Map<String, Object?> _oferta({String id = 'r1'}) => {
  'ride_id': id,
  'price_cents': 700,
  'payment_method': 'cash',
  'pickup': _lugar,
  'destination': _lugar,
  'distance_m': 2000,
  'seconds_to_pickup': 120,
  'will_queue': false,
  'expires_at': 4102444800.0, // ano 2100: o contador não importa nestes testes
};

Map<String, Object?> _aprovado({
  bool online = false,
  Map<String, Object?>? offer,
  Map<String, Object?>? ride,
  Map<String, Object?>? awaiting,
  String? blockedReason,
  String cnhExpiresOn = '2035-01-01',
}) => {
  'registration': {
    'status': 'approved',
    'online': online,
    'cnh_expires_on': cnhExpiresOn,
    'crlv_expires_on': '2035-01-01',
  },
  'account': {
    'completed_rides': 3,
    'trial_rides': 10,
    'entry_paid': false,
    'entry_fee_cents': 5000,
    'needs_entry': blockedReason == 'entry_pending',
    'blocked_reason': blockedReason,
    'cash_debt_cents': 0,
    'cash_debt_limit_cents': 70,
    'debt_to_pay_cents': 0,
  },
  'offer': offer,
  'ride': ride,
  'queued_ride': null,
  'awaiting_payment': awaiting,
};

Future<Mundo> _logado(WidgetTester tester, Map<String, Object?> estado) async {
  final m = Mundo();
  m.stateJson = estado;
  await m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
  await m.controller.start();
  await tester.pumpWidget(RiderApp(controller: m.controller));
  await tester.pump();
  return m;
}

Future<void> _fim(WidgetTester tester, Mundo m) =>
    tester.runAsync(() => m.controller.signOut());

http.Response _erro(int status, String code, String message) => json({
  'error': {'code': code, 'message': message},
}, status);

void main() {
  testWidgets('enquanto starting mostra a espera', (tester) async {
    final m = Mundo();
    await tester.pumpWidget(RiderApp(controller: m.controller));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('sem sessao mostra login e entrar leva ao cadastro', (
    tester,
  ) async {
    final m = Mundo();
    await m.controller.start();
    await tester.pumpWidget(RiderApp(controller: m.controller));
    await tester.pump();
    expect(find.byType(LoginScreen), findsOneWidget);

    await tester.enterText(find.byKey(const Key('telefone')), '75988510824');
    await tester.tap(find.text('Enviar código'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('codigo')), '123456');
    await tester.tap(find.text('Entrar'));
    await tester.pumpAndSettle();

    expect(find.byType(RegistrationScreen), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('pendente mostra a espera', (tester) async {
    final m = await _logado(tester, {
      ...estadoNaoCadastrado,
      'registration': {'status': 'pending'},
    });

    expect(find.byType(StatusScreen), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('aprovado mostra a home', (tester) async {
    final m = await _logado(tester, _aprovado());

    expect(find.byType(HomeScreen), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('rider_approved com a espera na tela vira a home', (
    tester,
  ) async {
    final m = await _logado(tester, {
      ...estadoNaoCadastrado,
      'registration': {'status': 'pending'},
    });
    expect(find.byType(StatusScreen), findsOneWidget);

    m.stateJson = _aprovado();
    m.canais.single.servidorMandaAviso('rider_approved', {});
    await tester.pumpAndSettle();

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.text('Seu cadastro foi aprovado!'), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('aceitar uma oferta abre a tela da corrida', (tester) async {
    final m = await _logado(tester, _aprovado(online: true, offer: _oferta()));
    m.on('POST', '/v1/rider/offers/r1/accept', (_) {
      m.stateJson = _aprovado(online: true, ride: _corrida());
      return json(_corrida());
    });

    await tester.tap(find.text('Aceitar'));
    await tester.pumpAndSettle();

    expect(find.byType(RideScreen), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets(
    'aceitar com 409 offer_gone mostra a mensagem, fica na home e nao abre a corrida',
    (tester) async {
      final m = await _logado(
        tester,
        _aprovado(online: true, offer: _oferta()),
      );
      m.on('POST', '/v1/rider/offers/r1/accept', (_) {
        m.stateJson = _aprovado(online: true); // a oferta venceu
        return _erro(
          409,
          'offer_gone',
          'Essa oferta não está mais disponível.',
        );
      });

      await tester.tap(find.text('Aceitar'));
      await tester.pumpAndSettle();

      expect(
        find.text('Essa oferta não está mais disponível.'),
        findsOneWidget,
      );
      expect(find.byType(RideScreen), findsNothing);
      expect(find.byType(OfferCard), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
      await _fim(tester, m);
    },
  );

  testWidgets(
    'passageiro cancelou com a tela da corrida aberta: volta para a home com o aviso',
    (tester) async {
      final m = await _logado(tester, _aprovado(ride: _corrida()));
      await tester.tap(find.text('Abrir corrida'));
      await tester.pumpAndSettle();
      expect(find.byType(RideScreen), findsOneWidget);

      m.stateJson = _aprovado();
      m.canais.single.servidorMandaAviso('ride_cancelled', {
        'ride_id': 'r1',
        'by': 'passenger',
        'fee_cents': 300,
      });
      await tester.pumpAndSettle();

      expect(find.byType(RideScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(
        find.text(
          'O passageiro cancelou a corrida. Taxa de cancelamento: R\$ 3,00.',
        ),
        findsOneWidget,
      );
      await _fim(tester, m);
    },
  );

  testWidgets(
    'cancelamento da corrida da fila nao tira o motoqueiro da corrida atual',
    (tester) async {
      final m = await _logado(
        tester,
        _aprovado(ride: _corrida(state: 'in_progress')),
      );
      await tester.tap(find.text('Abrir corrida'));
      await tester.pumpAndSettle();

      m.canais.single.servidorMandaAviso('ride_cancelled', {
        'ride_id': 'r2',
        'by': 'passenger',
      });
      await tester.pumpAndSettle();

      expect(find.byType(RideScreen), findsOneWidget);
      expect(
        find.text('O passageiro da próxima corrida cancelou.'),
        findsOneWidget,
      );
      await _fim(tester, m);
    },
  );

  testWidgets('passenger_blocked so avisa e nao fecha a corrida atual', (
    tester,
  ) async {
    final m = await _logado(
      tester,
      _aprovado(ride: _corrida(state: 'in_progress')),
    );
    await tester.tap(find.text('Abrir corrida'));
    await tester.pumpAndSettle();

    m.canais.single.servidorMandaAviso('passenger_blocked', {'ride_id': 'r0'});
    await tester.pumpAndSettle();

    expect(find.byType(RideScreen), findsOneWidget);
    expect(
      find.text(
        'O passageiro foi bloqueado por falta de pagamento. Você está livre.',
      ),
      findsOneWidget,
    );
    await _fim(tester, m);
  });

  testWidgets(
    'trip_completed abre avaliar com o ride_id certo e avaliar fecha a tela',
    (tester) async {
      final m = await _logado(tester, _aprovado());
      m.on('POST', '/v1/rides/r1/rating', (_) => http.Response('', 204));

      m.canais.single.servidorMandaAviso('trip_completed', {
        'ride_id': 'r1',
        'price_cents': 700,
        'method': 'pix',
      });
      await tester.pumpAndSettle();
      expect(find.byType(RateScreen), findsOneWidget);

      await tester.tap(find.byIcon(Icons.star).first);
      await tester.pumpAndSettle();

      final corpo = jsonDecode(
        m.sent('POST', '/v1/rides/r1/rating').single.body,
      ) as Map<String, Object?>;
      expect(corpo, {'stars': 1});
      expect(find.byType(RateScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
      await _fim(tester, m);
    },
  );

  testWidgets('trip_completed enquanto acompanha mantem a tela de avaliar', (
    tester,
  ) async {
    final m = await _logado(
      tester,
      _aprovado(ride: _corrida(state: 'in_progress')),
    );
    await tester.tap(find.text('Abrir corrida'));
    await tester.pumpAndSettle();
    expect(find.byType(RideScreen), findsOneWidget);

    // a corrida some do estado assim que termina, ao mesmo tempo que o aviso chega
    m.stateJson = _aprovado();
    m.canais.single.servidorMandaAviso('trip_completed', {
      'ride_id': 'r1',
      'price_cents': 700,
      'method': 'cash',
    });
    await tester.pumpAndSettle();

    expect(find.byType(RateScreen), findsOneWidget);
    expect(find.byType(RideScreen), findsNothing);
    await _fim(tester, m);
  });

  testWidgets('cobranca em dinheiro: Recebi o dinheiro manda cash-received', (
    tester,
  ) async {
    final m = await _logado(
      tester,
      _aprovado(
        awaiting: _corrida(
          state: 'completed',
          endPayment: {'amount_cents': 700},
        ),
      ),
    );
    m.on(
      'POST',
      '/v1/rider/rides/r1/cash-received',
      (_) => http.Response('', 204),
    );

    await tester.tap(find.text('Recebi o dinheiro'));
    await tester.pumpAndSettle();

    expect(m.sent('POST', '/v1/rider/rides/r1/cash-received'), hasLength(1));
    await _fim(tester, m);
  });

  testWidgets('entrada pendente: aviso do servidor, faixa e Pix da entrada', (
    tester,
  ) async {
    final m = await _logado(tester, _aprovado(blockedReason: 'entry_pending'));
    m.on(
      'POST',
      '/v1/rider/entry-charge',
      (_) => json({
        'charge_id': 'c1',
        'amount_cents': 5000,
        'br_code': '0002ENTRADA',
      }, 201),
    );

    m.canais.single.servidorMandaAviso('entry_required', {
      'entry_fee_cents': 5000,
    });
    await tester.pumpAndSettle();
    expect(
      find.text('Você precisa pagar a entrada para continuar.'),
      findsOneWidget,
    );

    await tester.tap(find.text('Pagar entrada'));
    await tester.pumpAndSettle();

    expect(find.byType(ChargeScreen), findsOneWidget);
    expect(find.textContaining('0002ENTRADA'), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('documento vencendo leva a renovar e fecha ao dar certo', (
    tester,
  ) async {
    final vence = DateTime.now().add(const Duration(days: 5));
    final m = await _logado(
      tester,
      _aprovado(
        cnhExpiresOn:
            '${vence.year.toString().padLeft(4, '0')}-'
            '${vence.month.toString().padLeft(2, '0')}-'
            '${vence.day.toString().padLeft(2, '0')}',
      ),
    );
    m.on('POST', '/v1/rider/documents/renew', (_) => http.Response('', 204));

    await tester.tap(find.text('Enviar novo'));
    await tester.pumpAndSettle();
    expect(find.byType(RenewDocumentsScreen), findsOneWidget);

    await tester.enterText(find.byKey(const Key('validade_cnh')), '01/01/2035');
    await tester.enterText(
      find.byKey(const Key('validade_crlv')),
      '01/01/2036',
    );
    await tester.tap(find.text('Enviar'));
    await tester.pumpAndSettle();

    expect(m.sent('POST', '/v1/rider/documents/renew'), hasLength(1));
    expect(find.byType(RenewDocumentsScreen), findsNothing);
    expect(find.byType(HomeScreen), findsOneWidget);
    await _fim(tester, m);
  });

  testWidgets('aviso offer vibra', (tester) async {
    final chamadas = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        chamadas.add(call);
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    final m = await _logado(tester, _aprovado(online: true));

    m.canais.single.servidorMandaAviso('offer', {'ride_id': 'r1'});
    await tester.pumpAndSettle();

    expect(chamadas.any((c) => c.method == 'HapticFeedback.vibrate'), isTrue);
    await _fim(tester, m);
  });

  testWidgets('401 volta ao login e a posicao para de ser enviada', (
    tester,
  ) async {
    final m = await _logado(tester, _aprovado(online: true));
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(m.sent('POST', '/v1/rider/position'), isNotEmpty);

    m.stateStatus = 401;
    m.canais.single.servidorMandaAviso('algum_aviso', {});
    // fora do relógio de mentira, para dar tempo real ao fechamento do tempo real (`.timeout` de verdade)
    await tester.runAsync(() async {
      await m.controller.refreshState().catchError((_) {});
      await Future<void>.delayed(const Duration(seconds: 3));
    });
    await tester.pump();
    expect(find.byType(LoginScreen), findsOneWidget);

    final antes = m.sent('POST', '/v1/rider/position').length;
    await tester.pump(const Duration(seconds: 12));

    expect(m.sent('POST', '/v1/rider/position').length, antes);
  });

  testWidgets('recusado cai no formulario com o motivo', (tester) async {
    final m = await _logado(tester, {
      ...estadoNaoCadastrado,
      'registration': {'status': 'rejected', 'reason': 'Foto da CNH ilegível.'},
    });

    expect(find.byType(RegistrationScreen), findsOneWidget);
    expect(find.byType(StatusScreen), findsNothing);
    expect(
      find.text(
        'Seu cadastro foi recusado: Foto da CNH ilegível. Corrija e envie de novo.',
      ),
      findsOneWidget,
    );
    await _fim(tester, m);
  });

  testWidgets(
    'renovar de quem esta bloqueado por documento vencido libera a conta',
    (tester) async {
      final m = await _logado(tester, {
        ...estadoNaoCadastrado,
        'registration': {'status': 'blocked', 'reason': 'documento vencido'},
      });
      expect(find.byType(StatusScreen), findsOneWidget);
      m.on('POST', '/v1/rider/documents/renew', (_) {
        m.stateJson = _aprovado(); // o servidor desbloqueou ao renovar
        return http.Response('', 204);
      });

      await tester.tap(find.text('Enviar documento novo'));
      await tester.pumpAndSettle();
      expect(find.byType(RenewDocumentsScreen), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('validade_cnh')),
        '01/01/2035',
      );
      await tester.enterText(
        find.byKey(const Key('validade_crlv')),
        '01/01/2036',
      );
      await tester.tap(find.text('Enviar'));
      await tester.pumpAndSettle();

      expect(find.byType(RenewDocumentsScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
      await _fim(tester, m);
    },
  );

  testWidgets('avisos do servidor sobre a conta viram mensagem', (
    tester,
  ) async {
    final m = await _logado(tester, _aprovado());

    m.canais.single.servidorMandaAviso('rider_unblocked', {});
    await tester.pumpAndSettle();
    expect(find.text('Sua conta foi liberada.'), findsOneWidget);
    await tester.pump(
      const Duration(seconds: 6),
    ); // o primeiro aviso sai da tela
    await tester.pumpAndSettle();

    m.canais.single.servidorMandaAviso('rider_rejected', {'reason': 'x'});
    await tester.pumpAndSettle();
    expect(
      find.text('Seu cadastro foi recusado. Veja o motivo e envie de novo.'),
      findsOneWidget,
    );
    await _fim(tester, m);
  });
}
