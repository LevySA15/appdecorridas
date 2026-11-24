import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:passenger/my_location.dart';
import 'package:passenger/screens/request_ride_screen.dart';

class _Fake implements MyLocation {
  _Fake(this.result);

  final Object result;
  var calls = 0;

  @override
  Future<Place> current() async {
    calls++;
    if (result is Place) return result as Place;
    throw result;
  }
}

Quote _quote() => const Quote(
  quoteId: 'q1',
  priceCents: 800,
  distanceM: 3000,
  durationS: 600,
  reason: 'normal',
  expiresAt: 9999999999,
  pickup: Place(lat: -12.96, lng: -39.26),
  destination: Place(lat: -12.97, lng: -39.27),
  etaSeconds: 120,
  nearbyRiders: 2,
  paymentMethods: ['pix', 'cash'],
);

Widget _screen(MyLocation? location, List<(Place, Place)> cotacoes) =>
    MaterialApp(
      theme: corridaTheme(Brightness.light),
      home: RequestRideScreen(
        myLocation: location,
        onQuote: (a, b) async {
          cotacoes.add((a, b));
          return _quote();
        },
        onConfirm: (_, _) async {},
      ),
    );

void main() {
  group('traduz o que o Android diz', () {
    test('GPS desligado', () {
      final p = problemOf(
        serviceEnabled: false,
        permission: LocationPermission.whileInUse,
      );
      expect(p?.message, contains('Ligue o GPS'));
    });

    test('permissão negada, negada para sempre e liberada', () {
      expect(
        problemOf(
          serviceEnabled: true,
          permission: LocationPermission.denied,
        )?.message,
        contains('permissão'),
      );
      expect(
        problemOf(
          serviceEnabled: true,
          permission: LocationPermission.deniedForever,
        )?.message,
        contains('configurações'),
      );
      expect(
        problemOf(
          serviceEnabled: true,
          permission: LocationPermission.whileInUse,
        ),
        isNull,
      );
      expect(
        problemOf(serviceEnabled: true, permission: LocationPermission.always),
        isNull,
      );
    });
  });

  testWidgets('sem fonte de localização o botão não existe', (tester) async {
    await tester.pumpWidget(_screen(null, []));

    expect(find.text('Estou aqui'), findsNothing);
  });

  testWidgets('estou aqui marca o embarque e o destino pede a cotação', (
    tester,
  ) async {
    final cotacoes = <(Place, Place)>[];
    final fonte = _Fake(const Place(lat: -12.9644, lng: -39.2597));
    await tester.pumpWidget(_screen(fonte, cotacoes));

    await tester.tap(find.text('Estou aqui'));
    await tester.pumpAndSettle();

    expect(fonte.calls, 1);
    expect(cotacoes, isEmpty); // só o embarque: ainda falta o destino
    // o toque seguinte marca o destino e aí sim cota
    final rect = tester.getRect(find.byType(FakeMapPicker));
    await tester.tapAt(rect.topLeft + const Offset(60, 120));
    await tester.pumpAndSettle();

    expect(cotacoes, hasLength(1));
    expect(cotacoes.single.$1.lat, closeTo(-12.9644, 1e-9));
    expect(find.text('Pedir corrida'), findsOneWidget);
  });

  testWidgets('erro de localização mostra a frase e não marca nada', (
    tester,
  ) async {
    final cotacoes = <(Place, Place)>[];
    await tester.pumpWidget(
      _screen(
        _Fake(const MyLocationUnavailable('Ligue o GPS do celular.')),
        cotacoes,
      ),
    );

    await tester.tap(find.text('Estou aqui'));
    await tester.pumpAndSettle();

    expect(find.text('Ligue o GPS do celular.'), findsOneWidget);
    expect(cotacoes, isEmpty);
  });

  testWidgets('com a cotação na tela o botão Estou aqui some', (tester) async {
    final cotacoes = <(Place, Place)>[];
    final fonte = _Fake(const Place(lat: -12.9644, lng: -39.2597));
    await tester.pumpWidget(_screen(fonte, cotacoes));
    await tester.tap(find.text('Estou aqui'));
    await tester.pumpAndSettle();
    final rect = tester.getRect(find.byType(FakeMapPicker));
    await tester.tapAt(rect.topLeft + const Offset(60, 120));
    await tester.pumpAndSettle();
    expect(find.text('R\$ 8,00'), findsOneWidget); // cotação na tela

    // a cotação cobre o botão: volta a marcar pela folha? o botão some quando há cotação
    expect(find.text('Estou aqui'), findsNothing);
  });
}
