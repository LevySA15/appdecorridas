import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corrida_ui/corrida_ui.dart';

void main() {
  test('toque no centro do quadrado da o centro da cidade', () {
    final place = pointFromTap(
      const Offset(50, 50),
      const Size(100, 100),
    );
    expect((place.lat - cityCenter.lat).abs(), lessThan(1e-6));
    expect((place.lng - cityCenter.lng).abs(), lessThan(1e-6));
  });

  test('toque no canto superior direito fica a nordeste', () {
    final place = pointFromTap(
      const Offset(100, 0),
      const Size(100, 100),
    );
    expect(place.lat, greaterThan(cityCenter.lat));
    expect(place.lng, greaterThan(cityCenter.lng));
  });

  testWidgets('marcar origem e destino, e substituir o destino', (
    tester,
  ) async {
    final chamadas = <(Place?, Place?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
            width: 300,
            height: 300,
            child: FakeMapPicker(
              onChanged: (pickup, destination) =>
                  chamadas.add((pickup, destination)),
            ),
          ),
        ),
      ),
    );

    await tester.tapAt(const Offset(50, 50));
    await tester.pump();
    expect(chamadas, hasLength(1));
    expect(chamadas[0].$1, isNotNull);
    expect(chamadas[0].$2, isNull);

    await tester.tapAt(const Offset(200, 200));
    await tester.pump();
    expect(chamadas, hasLength(2));
    expect(chamadas[1].$1, isNotNull);
    expect(chamadas[1].$2, isNotNull);

    await tester.tapAt(const Offset(250, 10));
    await tester.pump();
    expect(chamadas, hasLength(3));
    expect(chamadas[2].$1, chamadas[1].$1);
    expect(chamadas[2].$2, isNot(chamadas[1].$2));
  });
}
