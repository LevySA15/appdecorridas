import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';

/// Ladrilhos sem rede: um PNG transparente de 1x1.
class _BlankTiles extends TileProvider {
  static final _png = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  );

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) =>
      MemoryImage(_png);
}

Widget _app(Widget child, {Brightness brightness = Brightness.light}) =>
    MaterialApp(
      theme: corridaTheme(brightness),
      home: Scaffold(body: SizedBox(width: 390, height: 700, child: child)),
    );

void main() {
  testWidgets('desenha os marcadores e o trajeto', (tester) async {
    await tester.pumpWidget(
      _app(
        OsmMapView(
          tileProvider: _BlankTiles(),
          markers: const [
            MapMarker(MarkerKind.pickup, Place(lat: -12.96, lng: -39.26)),
            MapMarker(MarkerKind.destination, Place(lat: -12.97, lng: -39.25)),
            MapMarker(MarkerKind.me, Place(lat: -12.964, lng: -39.255)),
          ],
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.byType(FlutterMap), findsOneWidget);
    expect(find.byType(MarkerLayer), findsOneWidget);
    expect(
      find.byType(PolylineLayer),
      findsOneWidget,
    ); // embarque + destino = trajeto
    expect(
      find.text('© OpenStreetMap'),
      findsOneWidget,
    ); // a licença pede a atribuição
    expect(tester.takeException(), isNull);
  });

  testWidgets('sem destino não há trajeto', (tester) async {
    await tester.pumpWidget(
      _app(
        OsmMapView(
          tileProvider: _BlankTiles(),
          markers: const [
            MapMarker(MarkerKind.pickup, Place(lat: -12.96, lng: -39.26)),
          ],
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.byType(PolylineLayer), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('toque no mapa entrega o ponto da cidade', (tester) async {
    Place? tocado;
    await tester.pumpWidget(
      _app(
        OsmMapView(
          tileProvider: _BlankTiles(),
          markers: const [],
          onTap: (place) => tocado = place,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    await tester.tapAt(tester.getCenter(find.byType(FlutterMap)));
    await tester.pump(const Duration(milliseconds: 400));

    expect(tocado, isNotNull);
    expect((tocado!.lat - cityCenter.lat).abs(), lessThan(1e-3));
    expect((tocado!.lng - cityCenter.lng).abs(), lessThan(1e-3));
  });

  testWidgets('escolher origem e destino, e trocar só o destino', (
    tester,
  ) async {
    final chamadas = <(Place?, Place?)>[];
    await tester.pumpWidget(
      _app(
        OsmMapPicker(
          tileProvider: _BlankTiles(),
          onChanged: (a, b) => chamadas.add((a, b)),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    final rect = tester.getRect(find.byType(FlutterMap));

    await tester.tapAt(rect.center - const Offset(60, 60));
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tapAt(rect.center + const Offset(60, 60));
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump(
      const Duration(milliseconds: 400),
    ); // a câmera enquadra os dois
    await tester.tapAt(rect.center + const Offset(100, 20));
    await tester.pump(const Duration(milliseconds: 400));

    expect(chamadas.length, 3);
    expect(chamadas[0].$1, isNotNull);
    expect(chamadas[0].$2, isNull);
    expect(chamadas[1].$2, isNotNull);
    expect(chamadas[2].$1, chamadas[1].$1); // o embarque fica
    expect(chamadas[2].$2, isNot(chamadas[1].$2)); // o destino troca
    expect(tester.takeException(), isNull);
  });

  testWidgets('tema escuro e celular pequeno não quebram', (tester) async {
    tester.view.devicePixelRatio = 2;
    tester.view.physicalSize = const Size(640, 1136);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: corridaTheme(Brightness.dark),
        home: Scaffold(
          body: OsmMapView(
            tileProvider: _BlankTiles(),
            bottomSpace: 380,
            markers: const [
              MapMarker(MarkerKind.pickup, Place(lat: -12.96, lng: -39.26)),
              MapMarker(
                MarkerKind.destination,
                Place(lat: -12.97, lng: -39.25),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(tester.takeException(), isNull);
  });

  test('o motor padrão nos testes e na depuração é o desenho de mentira', () {
    expect(defaultMapEngine, MapEngine.fake);
  });
}
