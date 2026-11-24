import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'fake_map.dart' show MapMarker, MarkerKind;

/// A regra de "escolher origem e destino" que o mapa de verdade (OpenStreetMap ou Google) segue: o primeiro toque marca o
/// embarque, o segundo o destino, e tocar de novo só troca o destino. [pickup] novo (ex.: "estou aqui") vira o embarque e
/// desmarca o destino. Quem desenha o mapa é o [builder], que recebe os marcadores, o toque e o ponto para onde a câmera vai.
class MapPicker extends StatefulWidget {
  const MapPicker({
    required this.onChanged,
    required this.builder,
    this.pickup,
    super.key,
  });

  final void Function(Place? pickup, Place? destination) onChanged;

  /// Quando muda para um ponto novo, ele vira o embarque (e o destino marcado antes sai).
  final Place? pickup;

  final Widget Function(
    BuildContext context,
    List<MapMarker> markers,
    ValueChanged<Place> onTap,
    Place? focus,
  )
  builder;

  @override
  State<MapPicker> createState() => _MapPickerState();
}

class _MapPickerState extends State<MapPicker> {
  Place? _pickup;
  Place? _destination;

  @override
  void initState() {
    super.initState();
    _pickup = widget.pickup;
    if (_pickup != null) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => widget.onChanged(_pickup, _destination),
      );
    }
  }

  @override
  void didUpdateWidget(covariant MapPicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    final novo = widget.pickup;
    if (novo != null && !identical(novo, oldWidget.pickup)) {
      setState(() {
        _pickup = novo;
        _destination = null;
      });
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => widget.onChanged(_pickup, _destination),
      );
    }
  }

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
  Widget build(BuildContext context) => widget.builder(
    context,
    [
      if (_pickup != null) MapMarker(MarkerKind.pickup, _pickup!),
      if (_destination != null)
        MapMarker(MarkerKind.destination, _destination!),
    ],
    _tap,
    widget.pickup,
  );
}
