import 'dart:async';

import 'package:flutter/services.dart' show PlatformViewCreatedCallback;
import 'package:flutter/widgets.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart';

/// O "Google Maps" dos testes: no lugar do mapa nativo entra um quadro vazio, e tudo o que o app manda para o mapa
/// (marcadores, linhas, opções, movimentos da câmera) fica guardado para o teste conferir. [tap] simula um toque no mapa.
class FakeGoogleMapsPlatform extends GoogleMapsFlutterPlatform {
  final markers = <MarkerId, Marker>{};
  final polylines = <PolylineId, Polyline>{};
  var configuration = const MapConfiguration();
  MapWidgetConfiguration? widgetConfiguration;
  final cameraCalls = <CameraUpdate>[];
  var builds = 0;

  final _taps = StreamController<MapTapEvent>.broadcast();
  final _created = <int>{};

  /// Toque do dedo no mapa, no ponto dado.
  void tap(LatLng position) => _taps.add(MapTapEvent(1, position));

  /// A última câmera pedida (movimento ou animação), ou `null`.
  CameraUpdate? get lastCamera => cameraCalls.isEmpty ? null : cameraCalls.last;

  @override
  Future<void> init(int mapId) async {}

  @override
  Widget buildViewWithConfiguration(
    int creationId,
    PlatformViewCreatedCallback onPlatformViewCreated, {
    required MapWidgetConfiguration widgetConfiguration,
    MapConfiguration mapConfiguration = const MapConfiguration(),
    MapObjects mapObjects = const MapObjects(),
  }) {
    builds++;
    if (_created.add(creationId)) {
      this.widgetConfiguration = widgetConfiguration;
      configuration = mapConfiguration;
      for (final marker in mapObjects.markers) {
        markers[marker.markerId] = marker;
      }
      for (final line in mapObjects.polylines) {
        polylines[line.polylineId] = line;
      }
      scheduleMicrotask(() => onPlatformViewCreated(creationId));
    }
    return const SizedBox.expand(key: ValueKey('google-map-falso'));
  }

  @override
  Future<void> updateMapConfiguration(
    MapConfiguration update, {
    required int mapId,
  }) async => configuration = configuration.applyDiff(update);

  @override
  Future<void> updateMarkers(
    MarkerUpdates updates, {
    required int mapId,
  }) async {
    for (final id in updates.markerIdsToRemove) {
      markers.remove(id);
    }
    for (final marker in [
      ...updates.markersToAdd,
      ...updates.markersToChange,
    ]) {
      markers[marker.markerId] = marker;
    }
  }

  @override
  Future<void> updatePolylines(
    PolylineUpdates updates, {
    required int mapId,
  }) async {
    for (final id in updates.polylineIdsToRemove) {
      polylines.remove(id);
    }
    for (final line in [
      ...updates.polylinesToAdd,
      ...updates.polylinesToChange,
    ]) {
      polylines[line.polylineId] = line;
    }
  }

  // O app não usa estas camadas: o falso só aceita e ignora.
  @override
  Future<void> updatePolygons(PolygonUpdates u, {required int mapId}) async {}

  @override
  Future<void> updateCircles(CircleUpdates u, {required int mapId}) async {}

  @override
  Future<void> updateHeatmaps(HeatmapUpdates u, {required int mapId}) async {}

  @override
  Future<void> updateClusterManagers(
    ClusterManagerUpdates u, {
    required int mapId,
  }) async {}

  @override
  Future<void> updateGroundOverlays(
    GroundOverlayUpdates u, {
    required int mapId,
  }) async {}

  @override
  Future<void> updateTileOverlays({
    required Set<TileOverlay> newTileOverlays,
    required int mapId,
  }) async {}

  @override
  Future<void> animateCamera(CameraUpdate update, {required int mapId}) async =>
      cameraCalls.add(update);

  @override
  Future<void> moveCamera(CameraUpdate update, {required int mapId}) async =>
      cameraCalls.add(update);

  @override
  void dispose({required int mapId}) {}

  @override
  Stream<MapTapEvent> onTap({required int mapId}) => _taps.stream;

  @override
  Stream<CameraMoveStartedEvent> onCameraMoveStarted({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<CameraMoveEvent> onCameraMove({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<CameraIdleEvent> onCameraIdle({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<MarkerTapEvent> onMarkerTap({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<InfoWindowTapEvent> onInfoWindowTap({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<MarkerDragStartEvent> onMarkerDragStart({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<MarkerDragEvent> onMarkerDrag({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<MarkerDragEndEvent> onMarkerDragEnd({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<PolylineTapEvent> onPolylineTap({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<PolygonTapEvent> onPolygonTap({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<CircleTapEvent> onCircleTap({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<MapLongPressEvent> onLongPress({required int mapId}) =>
      const Stream.empty();
  @override
  Stream<ClusterTapEvent> onClusterTap({required int mapId}) =>
      const Stream.empty();
}
