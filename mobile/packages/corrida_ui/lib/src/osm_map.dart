import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import 'fake_map.dart' show MapMarker, MarkerKind, cityCenter;
import 'theme.dart';

/// Servidor de ladrilhos do OpenStreetMap: serve para **desenvolvimento e teste fechado** (poucas pessoas). Antes de abrir ao
/// público, trocar por um provedor com contrato (e atenção: com o mapa do Google no servidor — rotas — o app inteiro precisa
/// ser Google; os termos do Google proíbem usar os serviços deles num app com mapa de outro fornecedor). Ver `docs/mapa.md`.
const osmTileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/// Identifica o app para o servidor de ladrilhos (a política de uso do OpenStreetMap exige).
const osmUserAgentPackage = 'br.com.reconcavo.corrida';

LatLng _latLng(Place place) => LatLng(place.lat, place.lng);

/// Mapa de verdade (ruas do OpenStreetMap) com os mesmos marcadores do mapa de mentira. Se [onTap] existir, devolve o
/// ponto tocado. Quando há dois ou mais marcadores, a câmera enquadra todos (deixando espaço embaixo para a folha de controles).
class OsmMapView extends StatefulWidget {
  const OsmMapView({
    required this.markers,
    this.onTap,
    this.bottomSpace = 0,
    this.tileProvider,
    super.key,
  });

  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;

  /// Espaço (em pontos) que a folha de baixo cobre: a câmera enquadra os marcadores na parte que sobra.
  final double bottomSpace;

  /// Só para teste: ladrilhos sem rede.
  final TileProvider? tileProvider;

  @override
  State<OsmMapView> createState() => _OsmMapViewState();
}

class _OsmMapViewState extends State<OsmMapView> {
  final _controller = MapController();
  var _ready = false;

  @override
  void didUpdateWidget(covariant OsmMapView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_sameMarkers(oldWidget.markers, widget.markers)) _frame();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  static bool _sameMarkers(List<MapMarker> a, List<MapMarker> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  /// Enquadra os marcadores quando há dois ou mais (o retângulo que os contém). Com um só a câmera fica onde a pessoa
  /// deixou: quem acabou de marcar o embarque ainda vai procurar o destino no mapa.
  void _frame() {
    if (!_ready || widget.markers.length < 2) return;
    final points = [for (final marker in widget.markers) _latLng(marker.place)];
    try {
      _controller.fitCamera(
        CameraFit.coordinates(
          coordinates: points,
          padding: EdgeInsets.fromLTRB(56, 96, 56, 56 + widget.bottomSpace),
          maxZoom: 17,
        ),
      );
    } on Object {
      // mapa ainda sem tamanho (primeiro quadro): o próximo toque ou mudança enquadra
    }
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final markers = widget.markers;
    MapMarker? pickup;
    MapMarker? destination;
    for (final marker in markers) {
      if (marker.kind == MarkerKind.pickup) pickup = marker;
      if (marker.kind == MarkerKind.destination) destination = marker;
    }
    final onTap = widget.onTap;
    return FlutterMap(
      mapController: _controller,
      options: MapOptions(
        initialCenter: _latLng(cityCenter),
        initialZoom: 14,
        minZoom: 8,
        maxZoom: 19,
        onMapReady: () {
          _ready = true;
          _frame();
        },
        onTap: onTap == null
            ? null
            : (_, point) =>
                  onTap(Place(lat: point.latitude, lng: point.longitude)),
        interactionOptions: const InteractionOptions(
          flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
        ),
      ),
      children: [
        TileLayer(
          urlTemplate: osmTileUrl,
          userAgentPackageName: osmUserAgentPackage,
          maxNativeZoom: 19,
          tileProvider: widget.tileProvider,
          tileBuilder: dark ? darkModeTileBuilder : null,
        ),
        if (pickup != null && destination != null)
          PolylineLayer(
            polylines: [
              Polyline(
                points: [_latLng(pickup.place), _latLng(destination.place)],
                strokeWidth: 5,
                color: corridaAccent,
                borderStrokeWidth: 3,
                borderColor: dark ? const Color(0xFF0C0F14) : Colors.white,
              ),
            ],
          ),
        MarkerLayer(
          markers: [
            for (final marker in markers)
              Marker(
                point: _latLng(marker.place),
                width: 40,
                height: 40,
                child: _MarkerGlyph(marker.kind, dark: dark),
              ),
          ],
        ),
        // a licença do OpenStreetMap pede a atribuição à vista
        SafeArea(
          child: Align(
            alignment: Alignment.topRight,
            child: IgnorePointer(
              child: Container(
                margin: const EdgeInsets.all(6),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: (dark ? Colors.black : Colors.white).withValues(
                    alpha: 0.6,
                  ),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '© OpenStreetMap',
                  style: TextStyle(
                    fontSize: 10,
                    color: dark ? Colors.white70 : Colors.black87,
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// O pino de cada tipo, igual ao do mapa de mentira: embarque (ponto vermelho), destino (quadrado) e a moto.
class _MarkerGlyph extends StatelessWidget {
  const _MarkerGlyph(this.kind, {required this.dark});

  final MarkerKind kind;
  final bool dark;

  @override
  Widget build(BuildContext context) {
    final ring = dark ? const Color(0xFF0C0F14) : Colors.white;
    final ink = dark ? Colors.white : const Color(0xFF14161A);
    final shadow = [
      BoxShadow(
        color: Colors.black.withValues(alpha: 0.3),
        blurRadius: 4,
        offset: const Offset(0, 2),
      ),
    ];
    return Center(
      child: switch (kind) {
        MarkerKind.pickup => Container(
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            color: ring,
            shape: BoxShape.circle,
            boxShadow: shadow,
          ),
          child: Center(
            child: Container(
              width: 14,
              height: 14,
              decoration: const BoxDecoration(
                color: corridaAccent,
                shape: BoxShape.circle,
              ),
            ),
          ),
        ),
        MarkerKind.destination => Container(
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            color: ring,
            borderRadius: BorderRadius.circular(7),
            boxShadow: shadow,
          ),
          child: Center(
            child: Container(
              width: 14,
              height: 14,
              decoration: BoxDecoration(
                color: ink,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
          ),
        ),
        MarkerKind.me => Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: ink,
            shape: BoxShape.circle,
            border: Border.all(color: ring, width: 3),
            boxShadow: shadow,
          ),
          child: Icon(
            Icons.two_wheeler_rounded,
            size: 18,
            color: dark ? const Color(0xFF14161A) : Colors.white,
          ),
        ),
      },
    );
  }
}

/// Escolher origem e destino no mapa de verdade: o primeiro toque marca o embarque, o segundo o destino, e tocar de novo
/// só troca o destino (igual ao `FakeMapPicker`).
class OsmMapPicker extends StatefulWidget {
  const OsmMapPicker({
    required this.onChanged,
    this.bottomSpace = 0,
    this.tileProvider,
    super.key,
  });

  final void Function(Place? pickup, Place? destination) onChanged;
  final double bottomSpace;
  final TileProvider? tileProvider;

  @override
  State<OsmMapPicker> createState() => _OsmMapPickerState();
}

class _OsmMapPickerState extends State<OsmMapPicker> {
  Place? _pickup;
  Place? _destination;

  void _tap(Place place) {
    setState(() {
      if (_pickup == null) {
        _pickup = place;
      } else {
        _destination = place;
      }
    });
    widget.onChanged(_pickup, _destination);
  }

  @override
  Widget build(BuildContext context) {
    return OsmMapView(
      bottomSpace: widget.bottomSpace,
      tileProvider: widget.tileProvider,
      markers: [
        if (_pickup != null) MapMarker(MarkerKind.pickup, _pickup!),
        if (_destination != null)
          MapMarker(MarkerKind.destination, _destination!),
      ],
      onTap: _tap,
    );
  }
}
