import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as g;

import 'support/fake_google_maps_platform.dart';

const _pickup = Place(lat: -12.96, lng: -39.26);
const _destination = Place(lat: -12.97, lng: -39.25);

Widget _app(Widget child, {Brightness brightness = Brightness.light}) =>
    MaterialApp(
      theme: corridaTheme(brightness),
      home: Scaffold(body: SizedBox(width: 390, height: 700, child: child)),
    );

void main() {
  late FakeGoogleMapsPlatform platform;

  setUp(() {
    platform = FakeGoogleMapsPlatform();
    g.GoogleMapsFlutterPlatform.instance = platform;
  });

  Future<void> pumpMap(
    WidgetTester tester,
    Widget map, {
    Brightness? mode,
  }) async {
    await tester.pumpWidget(_app(map, brightness: mode ?? Brightness.light));
    await tester.pump(); // o mapa avisa que ficou pronto
    await tester.pump();
  }

  group('GoogleMapView', () {
    testWidgets('desenha os marcadores e o trajeto', (tester) async {
      await pumpMap(
        tester,
        const GoogleMapView(
          markers: [
            MapMarker(MarkerKind.pickup, _pickup),
            MapMarker(MarkerKind.destination, _destination),
            MapMarker(MarkerKind.me, Place(lat: -12.964, lng: -39.255)),
          ],
        ),
      );

      expect(platform.markers, hasLength(3));
      expect(
        platform.markers.values.map((m) => m.position),
        containsAll([
          const g.LatLng(-12.96, -39.26),
          const g.LatLng(-12.97, -39.25),
        ]),
      );
      // embarque + destino = trajeto (a linha e o contorno dela)
      expect(platform.polylines, hasLength(2));
      expect(tester.takeException(), isNull);
    });

    testWidgets('sem destino não há trajeto', (tester) async {
      await pumpMap(
        tester,
        const GoogleMapView(markers: [MapMarker(MarkerKind.pickup, _pickup)]),
      );

      expect(platform.markers, hasLength(1));
      expect(platform.polylines, isEmpty);
    });

    testWidgets('sem marcador a câmera fica na cidade (sem enquadrar)', (
      tester,
    ) async {
      await pumpMap(tester, const GoogleMapView(markers: []));

      expect(platform.markers, isEmpty);
      expect(platform.cameraCalls, isEmpty);
      expect(
        platform.widgetConfiguration!.initialCameraPosition.target,
        const g.LatLng(-12.9644, -39.2597),
      );
    });

    testWidgets('com dois marcadores a câmera enquadra os dois', (
      tester,
    ) async {
      await pumpMap(
        tester,
        const GoogleMapView(
          markers: [
            MapMarker(MarkerKind.pickup, _pickup),
            MapMarker(MarkerKind.destination, _destination),
          ],
        ),
      );

      final camera = platform.lastCamera! as g.CameraUpdateNewLatLngBounds;
      expect(camera.bounds.southwest, const g.LatLng(-12.97, -39.26));
      expect(camera.bounds.northeast, const g.LatLng(-12.96, -39.25));
      expect(camera.padding, 56);
    });

    testWidgets('pontos quase iguais viram um zoom fixo (não o máximo)', (
      tester,
    ) async {
      await pumpMap(
        tester,
        const GoogleMapView(
          markers: [
            MapMarker(MarkerKind.pickup, Place(lat: -12.9600, lng: -39.2600)),
            MapMarker(
              MarkerKind.destination,
              Place(lat: -12.9601, lng: -39.2601),
            ),
          ],
        ),
      );

      final camera = platform.lastCamera! as g.CameraUpdateNewLatLngZoom;
      expect(camera.zoom, 16);
    });

    testWidgets('marcador novo enquadra de novo; o mesmo não mexe na câmera', (
      tester,
    ) async {
      Widget map(List<MapMarker> markers) =>
          _app(GoogleMapView(markers: markers));
      const first = MapMarker(MarkerKind.pickup, _pickup);
      const second = MapMarker(MarkerKind.destination, _destination);

      await tester.pumpWidget(map(const [first]));
      await tester.pump();
      await tester.pump();
      expect(platform.cameraCalls, isEmpty);

      await tester.pumpWidget(map(const [first, second]));
      await tester.pump();
      expect(platform.cameraCalls, hasLength(1));

      // a tela reconstrói com a mesma lista (o contador da oferta muda a cada segundo): a câmera não se mexe
      await tester.pumpWidget(map(const [first, second]));
      await tester.pump();
      expect(platform.cameraCalls, hasLength(1));
    });

    testWidgets('o toque no mapa vira um Place', (tester) async {
      Place? tocado;
      await pumpMap(
        tester,
        GoogleMapView(markers: const [], onTap: (place) => tocado = place),
      );

      platform.tap(const g.LatLng(-12.95, -39.27));
      await tester.pump();

      expect(tocado, const Place(lat: -12.95, lng: -39.27));
    });

    testWidgets(
      'a folha de baixo entra no padding do mapa (logotipo do Google fica à vista)',
      (tester) async {
        await pumpMap(
          tester,
          const GoogleMapView(markers: [], bottomSpace: 240),
        );

        expect(platform.configuration.padding?.bottom, 240);
      },
    );

    testWidgets(
      'modo escuro aplica o estilo escuro; o claro usa o padrão do Google',
      (tester) async {
        await pumpMap(
          tester,
          const GoogleMapView(markers: []),
          mode: Brightness.dark,
        );
        expect(platform.configuration.style, googleDarkMapStyle);

        final claro = FakeGoogleMapsPlatform();
        g.GoogleMapsFlutterPlatform.instance = claro;
        await tester.pumpWidget(const SizedBox());
        await pumpMap(tester, const GoogleMapView(markers: []));
        expect(claro.configuration.style, anyOf(isNull, isEmpty));
      },
    );

    test('o estilo escuro é um JSON válido (o Google recusa o estilo inteiro se tiver um erro)', () {
      final regras = jsonDecode(googleDarkMapStyle) as List<dynamic>;
      expect(regras, isNotEmpty);
      for (final regra in regras) {
        expect((regra as Map<String, dynamic>)['stylers'], isNotEmpty);
      }
    });

    testWidgets(
      'miniatura (interactive: false) não mexe no mapa nem na rolagem',
      (tester) async {
        await pumpMap(
          tester,
          const GoogleMapView(markers: [], interactive: false),
        );

        expect(platform.configuration.scrollGesturesEnabled, isFalse);
        expect(platform.configuration.zoomGesturesEnabled, isFalse);
        // e o toque passa direto para a lista
        final bloqueio = tester.widget<IgnorePointer>(
          find
              .ancestor(
                of: find.byKey(const ValueKey('google-map-falso')),
                matching: find.byType(IgnorePointer),
              )
              .first,
        );
        expect(bloqueio.ignoring, isTrue);
      },
    );

    testWidgets(
      'sem controles soltos: sem bússola, zoom, barra e botão de localização',
      (tester) async {
        await pumpMap(tester, const GoogleMapView(markers: []));

        expect(platform.configuration.compassEnabled, isFalse);
        expect(platform.configuration.zoomControlsEnabled, isFalse);
        expect(platform.configuration.mapToolbarEnabled, isFalse);
        expect(platform.configuration.myLocationButtonEnabled, isFalse);
        expect(platform.configuration.rotateGesturesEnabled, isFalse);
      },
    );

    testWidgets('os pinos desenhados chegam ao mapa no lugar do pino padrão', (
      tester,
    ) async {
      await pumpMap(
        tester,
        const GoogleMapView(markers: [MapMarker(MarkerKind.pickup, _pickup)]),
      );
      expect(
        platform.markers.values.single.icon,
        g.BitmapDescriptor.defaultMarker,
      );

      // o desenho do pino é assíncrono de verdade: o relógio do teste precisa andar fora do tempo falso
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 300)),
      );
      await tester.pump();

      expect(platform.markers.values.single.icon, isA<g.BytesMapBitmap>());
    });
  });

  group('GoogleMapPicker', () {
    testWidgets(
      '1º toque marca o embarque, 2º o destino, 3º só troca o destino',
      (tester) async {
        Place? pickup;
        Place? destination;
        await pumpMap(
          tester,
          GoogleMapPicker(
            onChanged: (p, d) {
              pickup = p;
              destination = d;
            },
          ),
        );

        platform.tap(const g.LatLng(-12.96, -39.26));
        await tester.pump();
        expect(pickup, const Place(lat: -12.96, lng: -39.26));
        expect(destination, isNull);

        platform.tap(const g.LatLng(-12.97, -39.25));
        await tester.pump();
        expect(destination, const Place(lat: -12.97, lng: -39.25));

        platform.tap(const g.LatLng(-12.98, -39.24));
        await tester.pump();
        expect(pickup, const Place(lat: -12.96, lng: -39.26));
        expect(destination, const Place(lat: -12.98, lng: -39.24));
        expect(platform.markers, hasLength(2));
      },
    );

    testWidgets(
      '"estou aqui" vira o embarque, tira o destino e leva a câmera até lá',
      (tester) async {
        Place? pickup;
        Place? destination;
        Widget picker(Place? aqui) => _app(
          GoogleMapPicker(
            pickup: aqui,
            onChanged: (p, d) {
              pickup = p;
              destination = d;
            },
          ),
        );

        await tester.pumpWidget(picker(null));
        await tester.pump();
        await tester.pump();
        platform.tap(const g.LatLng(-12.96, -39.26));
        await tester.pump();
        platform.tap(const g.LatLng(-12.97, -39.25));
        await tester.pump();
        expect(destination, isNotNull);

        const aqui = Place(lat: -12.95, lng: -39.27);
        await tester.pumpWidget(picker(aqui));
        await tester.pump();
        await tester.pump();

        expect(pickup, aqui);
        expect(destination, isNull);
        final camera = platform.lastCamera! as g.CameraUpdateNewLatLngZoom;
        expect(camera.latLng, const g.LatLng(-12.95, -39.27));
        expect(camera.zoom, 16);
      },
    );
  });

  group('qual mapa o app usa', () {
    MapEngine escolha({
      String choice = '',
      bool key = false,
      bool release = false,
      bool web = false,
    }) => resolveMapEngine(
      choice: choice,
      hasGoogleKey: key,
      release: release,
      web: web,
    );

    test('sem nada: depuração e testes usam o de mentira, o release usa o OpenStreetMap', () {
      expect(escolha(), MapEngine.fake);
      expect(escolha(release: true), MapEngine.osm);
    });

    test('com a chave do Google o mapa é o do Google', () {
      expect(escolha(key: true), MapEngine.google);
      expect(escolha(key: true, release: true), MapEngine.google);
    });

    test('MAP escolhido ganha da chave', () {
      expect(escolha(choice: 'osm', key: true), MapEngine.osm);
      expect(escolha(choice: 'fake', key: true), MapEngine.fake);
      expect(escolha(choice: 'google'), MapEngine.google);
    });

    test('na web o Google vira OpenStreetMap (a página de teste não carrega o script do Google)', () {
      expect(escolha(choice: 'google', web: true), MapEngine.osm);
      expect(escolha(key: true, web: true), MapEngine.osm);
      expect(escolha(choice: 'fake', web: true), MapEngine.fake);
    });
  });

  group('CorridaMapView / CorridaMapPicker com engine google', () {
    testWidgets('a vista usa o mapa do Google', (tester) async {
      await pumpMap(
        tester,
        const CorridaMapView(
          engine: MapEngine.google,
          markers: [MapMarker(MarkerKind.pickup, _pickup)],
        ),
      );
      expect(find.byType(GoogleMapView), findsOneWidget);
      expect(platform.markers, hasLength(1));
    });

    testWidgets('o seletor usa o mapa do Google', (tester) async {
      await pumpMap(
        tester,
        CorridaMapPicker(engine: MapEngine.google, onChanged: (_, _) {}),
      );
      expect(find.byType(GoogleMapPicker), findsOneWidget);
    });
  });
}
