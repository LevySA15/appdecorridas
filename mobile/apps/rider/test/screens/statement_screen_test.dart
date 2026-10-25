import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/statement_screen.dart';

final _hoje = DateTime(2026, 10, 25, 15, 0);

StatementRide _corrida({
  String id = 'r1',
  double? em,
  String metodo = 'pix',
  int preco = 700,
  int taxa = 100,
  int metros = 2300,
  bool confirmada = true,
}) => StatementRide(
  rideId: id,
  completedAt: em ?? DateTime(2026, 10, 25, 9, 5).millisecondsSinceEpoch / 1000,
  priceCents: preco,
  feeCents: taxa,
  netCents: preco - taxa,
  method: metodo,
  distanceM: metros,
  confirmed: confirmada,
);

RiderStatement _extrato(
  String data, {
  List<StatementRide> corridas = const [],
  int? proxima = 3,
  int? taxaProxima = 100,
  int divida = 0,
  int aReceber = 0,
}) => RiderStatement(
  date: data,
  completedCount: corridas.length,
  grossCents: corridas.fold(0, (a, c) => a + c.priceCents),
  feeCents: corridas.fold(0, (a, c) => a + c.feeCents),
  netCents: corridas.fold(0, (a, c) => a + c.netCents),
  cashCents: corridas
      .where((c) => c.method == 'cash')
      .fold(0, (a, c) => a + c.priceCents),
  pixCents: corridas
      .where((c) => c.method != 'cash')
      .fold(0, (a, c) => a + c.priceCents),
  rides: corridas,
  nextRideNumber: proxima,
  nextFeeCents: taxaProxima,
  cashDebtCents: divida,
  pendingCents: aReceber,
);

Future<void> _pump(
  WidgetTester tester,
  Future<RiderStatement> Function(DateTime day) onLoad,
) async {
  tester.view.physicalSize = const Size(800, 2000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      home: StatementScreen(onLoad: onLoad, clock: () => _hoje),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('abre no dia de hoje e mostra os totais', (tester) async {
    DateTime? pedido;
    await _pump(tester, (dia) async {
      pedido = dia;
      return _extrato(
        '2026-10-25',
        corridas: [
          _corrida(),
          _corrida(id: 'r2', metodo: 'cash', preco: 900, taxa: 100),
        ],
        divida: 100,
      );
    });

    expect(pedido, DateTime(2026, 10, 25));
    expect(find.text('25/10/2026'), findsOneWidget);
    expect(find.text('Corridas: 2'), findsOneWidget);
    expect(find.text('Total das corridas: R\$ 16,00'), findsOneWidget);
    expect(find.text('Taxa do app: R\$ 2,00'), findsOneWidget);
    expect(find.text('Seu ganho: R\$ 14,00'), findsOneWidget);
    expect(
      find.text('No Pix: R\$ 7,00 · Em dinheiro: R\$ 9,00'),
      findsOneWidget,
    );
    expect(find.text('Taxas devidas: R\$ 1,00'), findsOneWidget);
  });

  testWidgets('mostra cada corrida com hora, valores e distancia', (
    tester,
  ) async {
    await _pump(
      tester,
      (_) async => _extrato('2026-10-25', corridas: [_corrida()]),
    );

    expect(find.text('09:05 · R\$ 7,00 · Pix'), findsOneWidget);
    expect(
      find.text('Ganho R\$ 6,00 (taxa R\$ 1,00) · 2,3 km'),
      findsOneWidget,
    );
  });

  testWidgets('hoje diz qual a taxa da proxima corrida', (tester) async {
    await _pump(
      tester,
      (_) async => _extrato('2026-10-25', proxima: 6, taxaProxima: 90),
    );

    expect(
      find.text('Próxima corrida (6ª do dia): taxa de R\$ 0,90'),
      findsOneWidget,
    );
  });

  testWidgets('dia sem corrida diz que nao teve', (tester) async {
    await _pump(tester, (_) async => _extrato('2026-10-25'));

    expect(find.text('Nenhuma corrida neste dia.'), findsOneWidget);
  });

  testWidgets('dia anterior carrega o dia de ontem e sem proxima faixa', (
    tester,
  ) async {
    final pedidos = <DateTime>[];
    await _pump(tester, (dia) async {
      pedidos.add(dia);
      return dia == DateTime(2026, 10, 25)
          ? _extrato('2026-10-25')
          : _extrato('2026-10-24', proxima: null, taxaProxima: null);
    });

    await tester.tap(find.text('Dia anterior'));
    await tester.pumpAndSettle();

    expect(pedidos, [DateTime(2026, 10, 25), DateTime(2026, 10, 24)]);
    expect(find.text('24/10/2026'), findsOneWidget);
    expect(find.textContaining('Próxima corrida'), findsNothing);
  });

  testWidgets('hoje nao tem proximo dia; ontem tem', (tester) async {
    await _pump(
      tester,
      (dia) async => _extrato(
        '${dia.year}-${dia.month}-${dia.day}',
        proxima: null,
        taxaProxima: null,
      ),
    );
    expect(
      tester
          .widget<TextButton>(find.widgetWithText(TextButton, 'Próximo dia'))
          .onPressed,
      isNull,
    );

    await tester.tap(find.text('Dia anterior'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<TextButton>(find.widgetWithText(TextButton, 'Próximo dia'))
          .onPressed,
      isNotNull,
    );

    await tester.tap(find.text('Próximo dia'));
    await tester.pumpAndSettle();
    expect(find.text('25/10/2026'), findsOneWidget);
  });

  testWidgets('erro mostra a mensagem e tentar de novo recarrega', (
    tester,
  ) async {
    var tentativas = 0;
    await _pump(tester, (_) async {
      tentativas++;
      if (tentativas == 1) throw NetworkException('Sem internet.');
      return _extrato('2026-10-25');
    });

    expect(find.text('Sem internet.'), findsOneWidget);
    await tester.tap(find.text('Tentar de novo'));
    await tester.pumpAndSettle();

    expect(find.text('Sem internet.'), findsNothing);
    expect(find.text('Corridas: 0'), findsOneWidget);
  });

  testWidgets('dinheiro ainda nao recebido aparece como a receber', (
    tester,
  ) async {
    await _pump(
      tester,
      (_) async => _extrato(
        '2026-10-25',
        corridas: [_corrida(metodo: 'cash', confirmada: false)],
        aReceber: 700,
      ),
    );

    expect(find.text('A receber (dinheiro): R\$ 7,00'), findsOneWidget);
    expect(
      find.text('09:05 · R\$ 7,00 · Dinheiro · a receber'),
      findsOneWidget,
    );
  });

  testWidgets('trocar de dia nao deixa os numeros do dia anterior na tela', (
    tester,
  ) async {
    final segundo = Completer<RiderStatement>();
    await _pump(tester, (dia) {
      if (dia == DateTime(2026, 10, 25)) {
        return Future.value(_extrato('2026-10-25', corridas: [_corrida()]));
      }
      return segundo.future;
    });
    expect(find.text('Corridas: 1'), findsOneWidget);

    await tester.tap(find.text('Dia anterior'));
    await tester.pump();

    expect(find.text('24/10/2026'), findsOneWidget);
    expect(find.text('Corridas: 1'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    segundo.complete(_extrato('2026-10-24', proxima: null, taxaProxima: null));
    await tester.pumpAndSettle();
    expect(find.text('Corridas: 0'), findsOneWidget);
  });
}
