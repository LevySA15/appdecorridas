import 'dart:math' as math;

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

/// A cidade de mentira do simulador do servidor (`server/simulator/geo.py:12`).
const cityCenter = Place(lat: -12.9644, lng: -39.2597);

/// Até onde o mapa de mentira cobre, nos dois eixos, a partir do centro.
const fakeMapHalfSizeM = 3000.0;

const _earthRadiusM = 6371000.0;

double _degrees(double radians) => radians * 180 / math.pi;
double _radians(double degrees) => degrees * math.pi / 180;

double _east(Offset local, double side) =>
    (local.dx / side - 0.5) * 2 * fakeMapHalfSizeM;
double _north(Offset local, double side) =>
    (0.5 - local.dy / side) * 2 * fakeMapHalfSizeM;

/// Um toque dentro do quadrado `size` (lado = `size.shortestSide`) vira um ponto da cidade de mentira,
/// espelhando `offset()` de `server/simulator/geo.py`.
Place pointFromTap(Offset local, Size size) {
  final side = size.shortestSide;
  final eastM = _east(local, side);
  final northM = _north(local, side);
  final lat = cityCenter.lat + _degrees(northM / _earthRadiusM);
  final lng =
      cityCenter.lng +
      _degrees(eastM / (_earthRadiusM * math.cos(_radians(cityCenter.lat))));
  return Place(lat: lat, lng: lng);
}

/// O inverso de [pointFromTap]: onde, no quadrado `size`, cai um ponto já marcado — para desenhar o
/// pino no lugar em que a pessoa tocou.
Offset _offsetFromPoint(Place place, Size size) {
  final side = size.shortestSide;
  final northM = _radians(place.lat - cityCenter.lat) * _earthRadiusM;
  final eastM =
      _radians(place.lng - cityCenter.lng) *
      _earthRadiusM *
      math.cos(_radians(cityCenter.lat));
  final dx = side * (eastM / (2 * fakeMapHalfSizeM) + 0.5);
  final dy = side * (0.5 - northM / (2 * fakeMapHalfSizeM));
  return Offset(dx, dy);
}

/// Desenho esquemático da cidade de mentira: o primeiro toque marca a origem (pino verde), o segundo
/// marca o destino (pino vermelho); tocar de novo depois dos dois só substitui o destino.
class FakeMapPicker extends StatefulWidget {
  const FakeMapPicker({required this.onChanged, super.key});

  final void Function(Place? pickup, Place? destination) onChanged;

  @override
  State<FakeMapPicker> createState() => _FakeMapPickerState();
}

class _FakeMapPickerState extends State<FakeMapPicker> {
  Place? _pickup;
  Place? _destination;

  void _handleTapDown(TapDownDetails details, Size size) {
    final point = pointFromTap(details.localPosition, size);
    setState(() {
      if (_pickup == null) {
        _pickup = point;
      } else {
        _destination = point;
      }
    });
    widget.onChanged(_pickup, _destination);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        return GestureDetector(
          onTapDown: (details) => _handleTapDown(details, size),
          child: CustomPaint(
            size: size,
            painter: _FakeMapPainter(pickup: _pickup, destination: _destination),
          ),
        );
      },
    );
  }
}

class _FakeMapPainter extends CustomPainter {
  _FakeMapPainter({required this.pickup, required this.destination});

  final Place? pickup;
  final Place? destination;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Rect.fromLTWH(0, 0, size.width, size.height),
      Paint()..color = const Color(0xFFDDE8DD),
    );
    canvas.drawCircle(
      size.center(Offset.zero),
      4,
      Paint()..color = const Color(0xFF888888),
    );
    final pickupAtual = pickup;
    if (pickupAtual != null) {
      canvas.drawCircle(
        _offsetFromPoint(pickupAtual, size),
        6,
        Paint()..color = const Color(0xFF2E7D32),
      );
    }
    final destinoAtual = destination;
    if (destinoAtual != null) {
      canvas.drawCircle(
        _offsetFromPoint(destinoAtual, size),
        6,
        Paint()..color = const Color(0xFFC62828),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _FakeMapPainter oldDelegate) =>
      oldDelegate.pickup != pickup || oldDelegate.destination != destination;
}
