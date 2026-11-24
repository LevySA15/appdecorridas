import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart' as g;

import 'fake_map.dart' show MapMarker, MarkerKind, cityCenter;
import 'map_picker.dart';
import 'route_line.dart';
import 'theme.dart';

/// Chave do Google Maps (`--dart-define=GOOGLE_MAPS_API_KEY=...`). O Gradle lê a mesma opção e a põe no manifesto do
/// Android (ver `android/app/build.gradle.kts`); aqui ela só serve para o app saber que o mapa do Google está configurado.
const googleMapsApiKey = String.fromEnvironment('GOOGLE_MAPS_API_KEY');

/// Estilo do mapa no modo escuro (cores do app: fundo `0C0F14`, cartões `171C25`). No claro vale o estilo padrão do Google.
const googleDarkMapStyle = '''
[
  {"elementType":"geometry","stylers":[{"color":"#171c25"}]},
  {"elementType":"labels.icon","stylers":[{"visibility":"off"}]},
  {"elementType":"labels.text.fill","stylers":[{"color":"#9aa3b2"}]},
  {"elementType":"labels.text.stroke","stylers":[{"color":"#0c0f14"}]},
  {"featureType":"administrative","elementType":"geometry","stylers":[{"color":"#2a3240"}]},
  {"featureType":"poi","elementType":"labels.text.fill","stylers":[{"color":"#7f8896"}]},
  {"featureType":"poi.park","elementType":"geometry","stylers":[{"color":"#16251f"}]},
  {"featureType":"road","elementType":"geometry","stylers":[{"color":"#2a3240"}]},
  {"featureType":"road","elementType":"geometry.stroke","stylers":[{"color":"#10141b"}]},
  {"featureType":"road","elementType":"labels.text.fill","stylers":[{"color":"#b4bcc9"}]},
  {"featureType":"road.highway","elementType":"geometry","stylers":[{"color":"#3a4456"}]},
  {"featureType":"transit","elementType":"geometry","stylers":[{"color":"#1d2430"}]},
  {"featureType":"water","elementType":"geometry","stylers":[{"color":"#0e1a2b"}]},
  {"featureType":"water","elementType":"labels.text.fill","stylers":[{"color":"#4e6d8c"}]}
]
''';

g.LatLng _latLng(Place place) => g.LatLng(place.lat, place.lng);

/// Mapa de verdade do Google (Maps SDK) com os mesmos marcadores do mapa de mentira. Se [onTap] existir, devolve o ponto
/// tocado. Com dois ou mais marcadores a câmera enquadra todos, deixando espaço embaixo para a folha de controles
/// ([bottomSpace]): o espaço entra no `padding` do próprio mapa, e assim o logotipo do Google (que os termos mandam
/// manter à vista) fica acima da folha e não escondido atrás dela.
class GoogleMapView extends StatefulWidget {
  const GoogleMapView({
    required this.markers,
    this.onTap,
    this.route = const [],
    this.bottomSpace = 0,
    this.interactive = true,
    this.focus,
    this.framePadding = const EdgeInsets.fromLTRB(56, 96, 56, 56),
    super.key,
  });

  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;

  /// O traçado pelas ruas entre embarque e destino (vazio: linha reta).
  final List<Place> route;

  /// Espaço (em pontos) que a folha de baixo cobre.
  final double bottomSpace;

  /// `false` para miniatura dentro de lista: o toque passa direto para a lista (senão brigaria com a rolagem).
  final bool interactive;

  /// Quando muda para um ponto novo, a câmera vai até ele (ex.: "estou aqui" achou a posição da pessoa).
  final Place? focus;

  /// Folga em volta dos marcadores ao enquadrar (o padrão deixa espaço para a barra de cima e a dica).
  final EdgeInsets framePadding;

  @override
  State<GoogleMapView> createState() => _GoogleMapViewState();
}

class _GoogleMapViewState extends State<GoogleMapView> {
  g.GoogleMapController? _controller;
  var _framed = false;

  // Os pinos são desenhados uma vez por (tipo, tema, densidade) e guardados: até ficarem prontos o mapa usa o pino padrão.
  final _icons = <_IconKey, g.BitmapDescriptor>{};
  final _loading = <_IconKey>{};

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final dark = Theme.of(context).brightness == Brightness.dark;
    final ratio = MediaQuery.devicePixelRatioOf(context);
    for (final kind in MarkerKind.values) {
      _ensureIcon(_IconKey(kind, dark, ratio));
    }
  }

  Future<void> _ensureIcon(_IconKey key) async {
    if (_icons.containsKey(key) || !_loading.add(key)) return;
    try {
      final icon = await _renderIcon(key);
      if (!mounted) return;
      setState(() => _icons[key] = icon);
    } on Object {
      // sem o pino desenhado, fica o pino padrão do Google: o mapa continua útil
    } finally {
      _loading.remove(key);
    }
  }

  @override
  void didUpdateWidget(covariant GoogleMapView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_sameMarkers(oldWidget.markers, widget.markers) ||
        !listEquals(oldWidget.route, widget.route)) {
      _frame(animate: true);
    }
    final focus = widget.focus;
    if (focus != null && !identical(focus, oldWidget.focus)) {
      _go(g.CameraUpdate.newLatLngZoom(_latLng(focus), 16), animate: true);
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  static bool _sameMarkers(List<MapMarker> a, List<MapMarker> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  Future<void> _go(g.CameraUpdate update, {required bool animate}) async {
    final controller = _controller;
    if (controller == null) return;
    try {
      if (animate) {
        await controller.animateCamera(update);
      } else {
        await controller.moveCamera(update);
      }
    } on Object {
      // mapa ainda sem tamanho: a próxima mudança enquadra
    }
  }

  /// Enquadra os marcadores quando há dois ou mais. Com um só a câmera fica onde a pessoa deixou: quem acabou de marcar o
  /// embarque ainda vai procurar o destino no mapa. Pontos quase iguais viram um zoom fixo (o Google chegaria ao máximo).
  void _frame({required bool animate}) {
    final markers = widget.markers;
    if (_controller == null || markers.length < 2) return;
    var south = 90.0, north = -90.0, west = 180.0, east = -180.0;
    for (final place in placesToFrame(markers, widget.route)) {
      south = math.min(south, place.lat);
      north = math.max(north, place.lat);
      west = math.min(west, place.lng);
      east = math.max(east, place.lng);
    }
    final tiny = (north - south) < 0.0015 && (east - west) < 0.0015;
    _go(
      tiny
          ? g.CameraUpdate.newLatLngZoom(
              g.LatLng((south + north) / 2, (west + east) / 2),
              16,
            )
          : g.CameraUpdate.newLatLngBounds(
              g.LatLngBounds(
                southwest: g.LatLng(south, west),
                northeast: g.LatLng(north, east),
              ),
              _fitPadding,
            ),
      animate: animate,
    );
  }

  double get _fitPadding => math.min(
    widget.framePadding.left,
    math.min(widget.framePadding.right, widget.framePadding.bottom),
  );

  void _created(g.GoogleMapController controller) {
    _controller = controller;
    if (_framed) return;
    _framed = true;
    _frame(animate: false);
  }

  g.BitmapDescriptor _icon(MarkerKind kind, bool dark, double ratio) =>
      _icons[_IconKey(kind, dark, ratio)] ?? g.BitmapDescriptor.defaultMarker;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final ratio = MediaQuery.devicePixelRatioOf(context);
    final markers = widget.markers;
    final ends = tripEnds(markers);
    final line = ends == null
        ? const <g.LatLng>[]
        : [
            for (final place in routeLine(
              ends.pickup,
              ends.destination,
              widget.route,
            ))
              _latLng(place),
          ];
    final onTap = widget.onTap;
    final topSpace = math.max(0.0, widget.framePadding.top - _fitPadding);
    return IgnorePointer(
      ignoring: !widget.interactive,
      child: g.GoogleMap(
        initialCameraPosition: g.CameraPosition(
          target: _latLng(cityCenter),
          zoom: 14,
        ),
        style: dark ? googleDarkMapStyle : null,
        padding: EdgeInsets.only(top: topSpace, bottom: widget.bottomSpace),
        onMapCreated: _created,
        onTap: onTap == null
            ? null
            : (point) =>
                  onTap(Place(lat: point.latitude, lng: point.longitude)),
        minMaxZoomPreference: const g.MinMaxZoomPreference(8, 19),
        compassEnabled: false,
        mapToolbarEnabled: false,
        zoomControlsEnabled: false,
        myLocationButtonEnabled: false,
        rotateGesturesEnabled: false,
        tiltGesturesEnabled: false,
        indoorViewEnabled: false,
        buildingsEnabled: false,
        scrollGesturesEnabled: widget.interactive,
        zoomGesturesEnabled: widget.interactive,
        polylines: {
          if (line.isNotEmpty) ...[
            // a linha ganha um contorno (claro no claro, escuro no escuro) para aparecer sobre qualquer rua
            g.Polyline(
              polylineId: const g.PolylineId('trajeto-contorno'),
              points: line,
              width: 9,
              color: dark ? const Color(0xFF0C0F14) : Colors.white,
              jointType: g.JointType.round,
              startCap: g.Cap.roundCap,
              endCap: g.Cap.roundCap,
              zIndex: 1,
            ),
            g.Polyline(
              polylineId: const g.PolylineId('trajeto'),
              points: line,
              width: 5,
              color: corridaAccent,
              jointType: g.JointType.round,
              startCap: g.Cap.roundCap,
              endCap: g.Cap.roundCap,
              zIndex: 2,
            ),
          ],
        },
        markers: {
          for (var i = 0; i < markers.length; i++)
            g.Marker(
              markerId: g.MarkerId('${markers[i].kind.name}-$i'),
              position: _latLng(markers[i].place),
              icon: _icon(markers[i].kind, dark, ratio),
              anchor: const Offset(0.5, 0.5),
              zIndexInt: markers[i].kind == MarkerKind.me ? 3 : 2,
            ),
        },
      ),
    );
  }
}

/// Escolher origem e destino no mapa do Google: a mesma regra do `OsmMapPicker` (ver [MapPicker]).
class GoogleMapPicker extends StatelessWidget {
  const GoogleMapPicker({
    required this.onChanged,
    this.bottomSpace = 0,
    this.pickup,
    this.route = const [],
    super.key,
  });

  final void Function(Place? pickup, Place? destination) onChanged;
  final double bottomSpace;

  /// O traçado pelas ruas da cotação (vazio: linha reta entre embarque e destino).
  final List<Place> route;

  /// Quando muda para um ponto novo, ele vira o embarque (e o destino marcado antes sai).
  final Place? pickup;

  @override
  Widget build(BuildContext context) => MapPicker(
    onChanged: onChanged,
    pickup: pickup,
    builder: (context, markers, onTap, focus) => GoogleMapView(
      bottomSpace: bottomSpace,
      focus: focus,
      markers: markers,
      route: route,
      onTap: onTap,
    ),
  );
}

@immutable
class _IconKey {
  const _IconKey(this.kind, this.dark, this.ratio);

  final MarkerKind kind;
  final bool dark;
  final double ratio;

  @override
  bool operator ==(Object other) =>
      other is _IconKey &&
      other.kind == kind &&
      other.dark == dark &&
      other.ratio == ratio;

  @override
  int get hashCode => Object.hash(kind, dark, ratio);
}

/// Desenha o pino (igual ao do mapa de mentira e ao do OpenStreetMap) numa imagem PNG para o Google usar como ícone.
Future<g.BitmapDescriptor> _renderIcon(_IconKey key) async {
  const size = 40.0;
  final dark = key.dark;
  final ring = dark ? const Color(0xFF0C0F14) : Colors.white;
  final ink = dark ? Colors.white : const Color(0xFF14161A);
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder)..scale(key.ratio);
  const center = Offset(size / 2, size / 2);

  void shadow(Path path) => canvas.drawShadow(path, Colors.black, 3, true);

  switch (key.kind) {
    case MarkerKind.pickup:
      final outer = Path()
        ..addOval(Rect.fromCircle(center: center, radius: 12));
      shadow(outer);
      canvas
        ..drawPath(outer, Paint()..color = ring)
        ..drawCircle(center, 7, Paint()..color = corridaAccent);
    case MarkerKind.destination:
      final outer = Path()
        ..addRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(center: center, width: 24, height: 24),
            const Radius.circular(7),
          ),
        );
      shadow(outer);
      canvas
        ..drawPath(outer, Paint()..color = ring)
        ..drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(center: center, width: 14, height: 14),
            const Radius.circular(3),
          ),
          Paint()..color = ink,
        );
    case MarkerKind.me:
      final outer = Path()
        ..addOval(Rect.fromCircle(center: center, radius: 17));
      shadow(outer);
      canvas
        ..drawPath(outer, Paint()..color = ring)
        ..drawCircle(center, 14, Paint()..color = ink);
      const icon = Icons.two_wheeler_rounded;
      final painter = TextPainter(
        text: TextSpan(
          text: String.fromCharCode(icon.codePoint),
          style: TextStyle(
            fontFamily: icon.fontFamily,
            package: icon.fontPackage,
            fontSize: 18,
            color: dark ? const Color(0xFF14161A) : Colors.white,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      painter.paint(
        canvas,
        center - Offset(painter.width / 2, painter.height / 2),
      );
  }

  final side = (size * key.ratio).ceil();
  final image = await recorder.endRecording().toImage(side, side);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  if (data == null) throw StateError('sem imagem do pino');
  return g.BitmapDescriptor.bytes(
    data.buffer.asUint8List(),
    imagePixelRatio: key.ratio,
    width: size,
    height: size,
  );
}
