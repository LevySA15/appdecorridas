import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/foundation.dart' show kIsWeb, kReleaseMode;
import 'package:flutter/material.dart';

import 'fake_map.dart';
import 'google_map.dart';
import 'osm_map.dart';

/// Qual mapa os apps desenham: `--dart-define=MAP=google` o do Google (precisa de `GOOGLE_MAPS_API_KEY`), `MAP=osm` as ruas
/// do OpenStreetMap, `MAP=fake` o desenho de mentira (sem internet, sempre igual: é o dos testes).
///
/// Sem `MAP`: com `--dart-define=GOOGLE_MAPS_API_KEY=...` o mapa é o do Google; senão o app de release usa o OpenStreetMap
/// e o de depuração (`flutter run`) e os testes o de mentira. Na web o Google não está ligado (a página de teste do
/// navegador não carrega o script do Google): lá `google` vira OpenStreetMap.
const _mapChoice = String.fromEnvironment('MAP');

enum MapEngine { fake, osm, google }

MapEngine get defaultMapEngine => resolveMapEngine(
  choice: _mapChoice,
  hasGoogleKey: googleMapsApiKey.isNotEmpty,
  release: kReleaseMode,
  web: kIsWeb,
);

/// A regra de [defaultMapEngine] com os dados à mão (para testar sem recompilar com outras opções).
MapEngine resolveMapEngine({
  required String choice,
  required bool hasGoogleKey,
  required bool release,
  required bool web,
}) {
  final engine = switch (choice) {
    'google' => MapEngine.google,
    'osm' => MapEngine.osm,
    'fake' => MapEngine.fake,
    _ =>
      hasGoogleKey
          ? MapEngine.google
          : (release ? MapEngine.osm : MapEngine.fake),
  };
  return engine == MapEngine.google && web ? MapEngine.osm : engine;
}

/// Mapa para ver (marcadores e, se [onTap], toque para "andar"): o de mentira ou o de verdade conforme [engine].
class CorridaMapView extends StatelessWidget {
  const CorridaMapView({
    required this.markers,
    this.onTap,
    this.route = const [],
    this.bottomSpace = 0,
    this.interactive = true,
    this.framePadding,
    this.engine,
    super.key,
  });

  /// Folga em volta dos marcadores ao enquadrar; `null` usa a de tela cheia (miniatura passa uma menor).
  final EdgeInsets? framePadding;

  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;

  /// O traçado pelas ruas entre embarque e destino (vazio: linha reta). Vem do servidor (`route` da cotação/corrida).
  final List<Place> route;

  /// `false` para miniatura numa lista (o mapa de verdade não reage ao dedo).
  final bool interactive;

  /// Quanto da parte de baixo a folha de controles cobre (o mapa de verdade enquadra os marcadores acima dela).
  final double bottomSpace;
  final MapEngine? engine;

  @override
  Widget build(BuildContext context) {
    final padding = framePadding ?? const EdgeInsets.fromLTRB(56, 96, 56, 56);
    return switch (engine ?? defaultMapEngine) {
      MapEngine.google => GoogleMapView(
        markers: markers,
        route: route,
        onTap: onTap,
        bottomSpace: bottomSpace,
        interactive: interactive,
        framePadding: padding,
      ),
      MapEngine.osm => OsmMapView(
        markers: markers,
        route: route,
        onTap: onTap,
        bottomSpace: bottomSpace,
        interactive: interactive,
        framePadding: padding,
      ),
      MapEngine.fake => FakeMapView(
        markers: markers,
        onTap: onTap,
        route: route,
      ),
    };
  }
}

/// Mapa para escolher embarque e destino.
class CorridaMapPicker extends StatelessWidget {
  const CorridaMapPicker({
    required this.onChanged,
    this.bottomSpace = 0,
    this.pickup,
    this.route = const [],
    this.engine,
    super.key,
  });

  final void Function(Place? pickup, Place? destination) onChanged;
  final double bottomSpace;

  /// O traçado pelas ruas da cotação (vazio: linha reta entre embarque e destino).
  final List<Place> route;

  /// Quando muda para um ponto novo, ele vira o embarque ("estou aqui").
  final Place? pickup;
  final MapEngine? engine;

  @override
  Widget build(BuildContext context) => switch (engine ?? defaultMapEngine) {
    MapEngine.google => GoogleMapPicker(
      onChanged: onChanged,
      bottomSpace: bottomSpace,
      pickup: pickup,
      route: route,
    ),
    MapEngine.osm => OsmMapPicker(
      onChanged: onChanged,
      bottomSpace: bottomSpace,
      pickup: pickup,
      route: route,
    ),
    MapEngine.fake => FakeMapPicker(
      onChanged: onChanged,
      pickup: pickup,
      route: route,
    ),
  };
}
