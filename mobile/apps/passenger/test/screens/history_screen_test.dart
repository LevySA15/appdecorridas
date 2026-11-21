import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/history_screen.dart';

RideHistoryItem _item(
  String id, {
  RideState state = RideState.completed,
  String pickup = 'Rua A',
  String destination = 'Feira livre',
  int price = 700,
}) => RideHistoryItem(
  rideId: id,
  state: state,
  createdAt: DateTime(2026, 11, 20, 18, 5).millisecondsSinceEpoch / 1000,
  priceCents: price,
  method: 'pix',
  pickupText: pickup,
  destinationText: destination,
  distanceM: 1950,
  rider: const HistoryRider(name: 'João', plate: 'ABC1D23', motoModel: 'CG'),
  myStars: null,
  feeCents: 0,
  feeRefunded: false,
  paymentPending: false,
);

RideHistoryPage _pagina(List<RideHistoryItem> itens, {bool hasMore = false}) =>
    RideHistoryPage(rides: itens, hasMore: hasMore);

Widget _app({
  required Future<RideHistoryPage> Function(int) onLoad,
  void Function(RideHistoryItem)? onOpenReceipt,
}) => MaterialApp(
  home: HistoryScreen(onLoad: onLoad, onOpenReceipt: onOpenReceipt ?? (_) {}),
);

void main() {
  testWidgets('pagina unica mostra as corridas e nao oferece ver mais', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        onLoad: (_) async => _pagina([_item('a'), _item('b', pickup: 'Rua B')]),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Rua A'), findsOneWidget);
    expect(find.text('Rua B'), findsOneWidget);
    expect(find.text('Ver mais'), findsNothing);
    expect(find.text(brl(700)), findsNWidgets(2));
  });

  testWidgets('ver mais pede o proximo deslocamento e acrescenta os itens', (
    tester,
  ) async {
    final pedidos = <int>[];
    await tester.pumpWidget(
      _app(
        onLoad: (offset) async {
          pedidos.add(offset);
          return offset == 0
              ? _pagina([
                  _item('a'),
                  _item('b', pickup: 'Rua B'),
                ], hasMore: true)
              : _pagina([_item('c', pickup: 'Rua C')]);
        },
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Ver mais'));
    await tester.pumpAndSettle();

    expect(pedidos, [0, 2]);
    expect(find.text('Rua A'), findsOneWidget);
    expect(find.text('Rua C'), findsOneWidget);
    expect(find.text('Ver mais'), findsNothing);
  });

  testWidgets('lista vazia diz que ainda nao ha corridas', (tester) async {
    await tester.pumpWidget(_app(onLoad: (_) async => _pagina(const [])));
    await tester.pumpAndSettle();

    expect(find.text('Você ainda não fez corridas.'), findsOneWidget);
  });

  testWidgets('falha na primeira pagina mostra o erro e tenta de novo', (
    tester,
  ) async {
    var chamadas = 0;
    await tester.pumpWidget(
      _app(
        onLoad: (_) async {
          chamadas++;
          if (chamadas == 1) throw NetworkException();
          return _pagina([_item('a')]);
        },
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text('Sem conexão com o servidor. Tente de novo.'),
      findsOneWidget,
    );
    await tester.tap(find.text('Tentar de novo'));
    await tester.pumpAndSettle();

    expect(find.text('Rua A'), findsOneWidget);
    expect(find.text('Tentar de novo'), findsNothing);
  });

  testWidgets(
    'falha na segunda pagina mantem a primeira e deixa tentar de novo',
    (tester) async {
      var segundaVez = 0;
      await tester.pumpWidget(
        _app(
          onLoad: (offset) async {
            if (offset == 0) return _pagina([_item('a')], hasMore: true);
            segundaVez++;
            if (segundaVez == 1) throw NetworkException();
            return _pagina([_item('c', pickup: 'Rua C')]);
          },
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Ver mais'));
      await tester.pumpAndSettle();

      expect(find.byType(SnackBar), findsOneWidget);
      expect(find.text('Rua A'), findsOneWidget);
      expect(find.text('Ver mais'), findsOneWidget);

      await tester.tap(find.text('Ver mais'));
      await tester.pumpAndSettle();
      expect(find.text('Rua C'), findsOneWidget);
    },
  );

  testWidgets('endereco de 200 letras nao estoura a tela', (tester) async {
    final longo = 'Rua ${'muito ' * 33}longa';
    await tester.pumpWidget(
      _app(
        onLoad: (_) async =>
            _pagina([_item('a', pickup: longo, destination: longo)]),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text(longo), findsOneWidget);
  });

  testWidgets('corrida cancelada nao mostra preco', (tester) async {
    await tester.pumpWidget(
      _app(
        onLoad: (_) async =>
            _pagina([_item('a', state: RideState.cancelled, price: 900)]),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Cancelada'), findsOneWidget);
    expect(find.text(brl(900)), findsNothing);
  });

  testWidgets('tocar numa corrida abre o recibo dela', (tester) async {
    RideHistoryItem? aberto;
    await tester.pumpWidget(
      _app(
        onLoad: (_) async => _pagina([_item('a'), _item('b', pickup: 'Rua B')]),
        onOpenReceipt: (ride) => aberto = ride,
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Rua B'));

    expect(aberto!.rideId, 'b');
  });
}
