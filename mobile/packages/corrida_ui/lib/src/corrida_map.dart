import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:flutter/material.dart';

import 'fake_map.dart';
import 'osm_map.dart';

/// Qual mapa os apps desenham. `--dart-define=MAP=osm` usa as ruas do OpenStreetMap, `--dart-define=MAP=fake` o desenho
/// de mentira (sem internet, sempre igual: é o dos testes). Sem a opção: o app de release usa o mapa de verdade e o de
/// depuração (`flutter run`) e os testes o de mentira.
const _mapChoice = String.fromEnvironment('MAP');

enum MapEngine { fake, osm }

MapEngine get defaultMapEngine => switch (_mapChoice) {
  'osm' => MapEngine.osm,
  'fake' => MapEngine.fake,
  _ => kReleaseMode ? MapEngine.osm : MapEngine.fake,
};

/// Mapa para ver (marcadores e, se [onTap], toque para "andar"): o de mentira ou o de verdade conforme [engine].
class CorridaMapView extends StatelessWidget {
  const CorridaMapView({
    required this.markers,
    this.onTap,
    this.bottomSpace = 0,
    this.engine,
    super.key,
  });

  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;

  /// Quanto da parte de baixo a folha de controles cobre (o mapa de verdade enquadra os marcadores acima dela).
  final double bottomSpace;
  final MapEngine? engine;

  @override
  Widget build(BuildContext context) =>
      (engine ?? defaultMapEngine) == MapEngine.osm
      ? OsmMapView(markers: markers, onTap: onTap, bottomSpace: bottomSpace)
      : FakeMapView(markers: markers, onTap: onTap);
}

/// Mapa para escolher embarque e destino.
class CorridaMapPicker extends StatelessWidget {
  const CorridaMapPicker({
    required this.onChanged,
    this.bottomSpace = 0,
    this.engine,
    super.key,
  });

  final void Function(Place? pickup, Place? destination) onChanged;
  final double bottomSpace;
  final MapEngine? engine;

  @override
  Widget build(BuildContext context) =>
      (engine ?? defaultMapEngine) == MapEngine.osm
      ? OsmMapPicker(onChanged: onChanged, bottomSpace: bottomSpace)
      : FakeMapPicker(onChanged: onChanged);
}
