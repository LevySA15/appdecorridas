import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:corrida_ui/src/route_line.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as g;

import 'support/fake_google_maps_platform.dart';

const _embarque = Place(lat: -12.9600, lng: -39.2600);
const _destino = Place(lat: -12.9700, lng: -39.2500);

/// Uma rua em "L": desce até a esquina e vira para leste (não é a linha reta).
const _ruas = [
  Place(lat: -12.9601, lng: -39.2600), // pertinho do embarque
  Place(lat: -12.9700, lng: -39.2600), // a esquina
  Place(lat: -12.9700, lng: -39.2501), // pertinho do destino
];

const _marcadores = [
  MapMarker(MarkerKind.pickup, _embarque),
  MapMarker(MarkerKind.destination, _destino),
];

Widget _app(Widget child, {Brightness brightness = Brightness.light}) =>
    MaterialApp(
      theme: corridaTheme(brightness),
      home: Scaffold(body: SizedBox(width: 390, height: 700, child: child)),
    );

void main() {
  group('routeLine', () {
    test('sem traçado, a linha reta entre embarque e destino', () {
      expect(routeLine(_embarque, _destino), [_embarque, _destino]);
      expect(routeLine(_embarque, _destino, const []), [_embarque, _destino]);
    });

    test('traçado de um ponto só não é traçado', () {
      expect(routeLine(_embarque, _destino, [_embarque]), [
        _embarque,
        _destino,
      ]);
    });

    test('traçado que combina com os dois pontos vale', () {
      expect(routeLine(_embarque, _destino, _ruas), _ruas);
    });

    test('as pontas podem diferir uns metros (o Google gruda na rua)', () {
      const embarque = Place(lat: -12.96009, lng: -39.26009); // ~14 m
      expect(routeLine(embarque, _destino, _ruas), _ruas);
    });

    test('traçado de outro pedido (pontas longe) cai na linha reta', () {
      const outro = Place(lat: -12.9, lng: -39.2); // ~9 km
      expect(routeLine(outro, _destino, _ruas), [outro, _destino]);
      expect(routeLine(_embarque, outro, _ruas), [_embarque, outro]);
    });
  });

  group('tripEnds e placesToFrame', () {
    test('sem embarque e destino não há linha', () {
      expect(tripEnds(const []), isNull);
      expect(tripEnds(const [MapMarker(MarkerKind.pickup, _embarque)]), isNull);
      expect(tripEnds(const [MapMarker(MarkerKind.me, _embarque)]), isNull);
    });

    test('com os dois, devolve as pontas (a moto não conta)', () {
      final ends = tripEnds([
        ..._marcadores,
        const MapMarker(MarkerKind.me, Place(lat: -12.9650, lng: -39.2550)),
      ])!;
      expect(ends.pickup, _embarque);
      expect(ends.destination, _destino);
    });

    test('a câmera enquadra os marcadores e as curvas do traçado', () {
      final places = placesToFrame(_marcadores, _ruas);
      expect(places, containsAll([_embarque, _destino, _ruas[1]]));
    });

    test('traçado que não combina fica de fora do enquadramento', () {
      const outro = [
        Place(lat: -12.0, lng: -39.0),
        Place(lat: -12.1, lng: -39.1),
      ];
      expect(placesToFrame(_marcadores, outro), [_embarque, _destino]);
    });
  });

  group('OpenStreetMap', () {
    testWidgets('desenha o traçado pelas ruas (não a linha reta)', (
      tester,
    ) async {
      await tester.pumpWidget(
        _app(const OsmMapView(markers: _marcadores, route: _ruas)),
      );
      await tester.pump();

      final linhas = tester.widget<PolylineLayer>(find.byType(PolylineLayer));
      final pontos = linhas.polylines.single.points;
      expect(pontos, hasLength(3));
      expect(pontos[1].latitude, -12.9700);
      expect(pontos[1].longitude, -39.2600);
      expect(tester.takeException(), isNull);
    });

    testWidgets('sem traçado desenha a reta de dois pontos', (tester) async {
      await tester.pumpWidget(_app(const OsmMapView(markers: _marcadores)));
      await tester.pump();

      final linhas = tester.widget<PolylineLayer>(find.byType(PolylineLayer));
      expect(linhas.polylines.single.points, hasLength(2));
    });

    testWidgets('traçado velho (de outro pedido) não aparece', (tester) async {
      const outro = [
        Place(lat: -12.0, lng: -39.0),
        Place(lat: -12.1, lng: -39.1),
      ];
      await tester.pumpWidget(
        _app(const OsmMapView(markers: _marcadores, route: outro)),
      );
      await tester.pump();

      final linhas = tester.widget<PolylineLayer>(find.byType(PolylineLayer));
      expect(linhas.polylines.single.points, hasLength(2));
    });

    testWidgets('o seletor leva o traçado ao mapa', (tester) async {
      await tester.pumpWidget(
        _app(
          OsmMapPicker(pickup: _embarque, route: _ruas, onChanged: (_, _) {}),
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(tester.widget<OsmMapView>(find.byType(OsmMapView)).route, _ruas);
    });
  });

  group('Google', () {
    late FakeGoogleMapsPlatform platform;

    setUp(() {
      platform = FakeGoogleMapsPlatform();
      g.GoogleMapsFlutterPlatform.instance = platform;
    });

    Future<void> pump(WidgetTester tester, Widget map) async {
      await tester.pumpWidget(_app(map));
      await tester.pump();
      await tester.pump();
    }

    testWidgets(
      'a linha segue as ruas (o contorno e a linha com os mesmos pontos)',
      (tester) async {
        await pump(
          tester,
          const GoogleMapView(markers: _marcadores, route: _ruas),
        );

        expect(platform.polylines, hasLength(2));
        for (final linha in platform.polylines.values) {
          expect(linha.points, hasLength(3));
          expect(linha.points[1], const g.LatLng(-12.9700, -39.2600));
        }
      },
    );

    testWidgets('sem traçado a linha é reta', (tester) async {
      await pump(tester, const GoogleMapView(markers: _marcadores));
      for (final linha in platform.polylines.values) {
        expect(linha.points, hasLength(2));
      }
    });

    testWidgets('a câmera enquadra também a esquina do traçado', (
      tester,
    ) async {
      // a esquina fica ao sul-oeste: sem ela o retângulo seria só embarque–destino (lat -12.97 a -12.96, lng -39.26 a -39.25)
      const esquina = [
        Place(lat: -12.9601, lng: -39.2600),
        Place(lat: -12.9800, lng: -39.2700),
        Place(lat: -12.9700, lng: -39.2501),
      ];
      await pump(
        tester,
        const GoogleMapView(markers: _marcadores, route: esquina),
      );

      final camera = platform.lastCamera! as g.CameraUpdateNewLatLngBounds;
      expect(camera.bounds.southwest, const g.LatLng(-12.9800, -39.2700));
      expect(camera.bounds.northeast, const g.LatLng(-12.9600, -39.2500));
    });

    testWidgets('o traçado chegando depois enquadra de novo', (tester) async {
      Widget mapa(List<Place> route) =>
          _app(GoogleMapView(markers: _marcadores, route: route));
      await tester.pumpWidget(mapa(const []));
      await tester.pump();
      await tester.pump();
      final antes = platform.cameraCalls.length;

      await tester.pumpWidget(mapa(_ruas));
      await tester.pump();
      expect(platform.cameraCalls.length, antes + 1);

      await tester.pumpWidget(
        mapa(_ruas),
      ); // a mesma lista: a câmera fica quieta
      await tester.pump();
      expect(platform.cameraCalls.length, antes + 1);
    });

    testWidgets('o seletor leva o traçado ao mapa', (tester) async {
      await pump(
        tester,
        GoogleMapPicker(pickup: _embarque, route: _ruas, onChanged: (_, _) {}),
      );
      expect(
        tester.widget<GoogleMapView>(find.byType(GoogleMapView)).route,
        _ruas,
      );
    });
  });

  group('mapa de mentira', () {
    for (final brightness in Brightness.values) {
      testWidgets('desenha o traçado sem erro (${brightness.name})', (
        tester,
      ) async {
        await tester.pumpWidget(
          _app(
            const FakeMapView(markers: _marcadores, route: _ruas),
            brightness: brightness,
          ),
        );
        await tester.pump();
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('troca de traçado repinta', (tester) async {
      await tester.pumpWidget(_app(const FakeMapView(markers: _marcadores)));
      await tester.pumpWidget(
        _app(const FakeMapView(markers: _marcadores, route: _ruas)),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  });

  group('CorridaMapView e CorridaMapPicker', () {
    testWidgets('passam o traçado ao motor escolhido', (tester) async {
      g.GoogleMapsFlutterPlatform.instance = FakeGoogleMapsPlatform();
      for (final engine in MapEngine.values) {
        await tester.pumpWidget(
          _app(
            CorridaMapView(engine: engine, markers: _marcadores, route: _ruas),
          ),
        );
        await tester.pump();
        await tester.pump();
        final desenhou = switch (engine) {
          MapEngine.fake =>
            tester.widget<FakeMapView>(find.byType(FakeMapView)).route,
          MapEngine.osm =>
            tester.widget<OsmMapView>(find.byType(OsmMapView)).route,
          MapEngine.google =>
            tester.widget<GoogleMapView>(find.byType(GoogleMapView)).route,
        };
        expect(desenhou, _ruas, reason: engine.name);
      }
    });

    testWidgets('o seletor também', (tester) async {
      g.GoogleMapsFlutterPlatform.instance = FakeGoogleMapsPlatform();
      for (final engine in MapEngine.values) {
        await tester.pumpWidget(
          _app(
            CorridaMapPicker(
              engine: engine,
              route: _ruas,
              onChanged: (_, _) {},
            ),
          ),
        );
        await tester.pump();
        await tester.pump();
        final desenhou = switch (engine) {
          MapEngine.fake =>
            tester.widget<FakeMapPicker>(find.byType(FakeMapPicker)).route,
          MapEngine.osm =>
            tester.widget<OsmMapPicker>(find.byType(OsmMapPicker)).route,
          MapEngine.google =>
            tester.widget<GoogleMapPicker>(find.byType(GoogleMapPicker)).route,
        };
        expect(desenhou, _ruas, reason: engine.name);
      }
    });
  });
}
