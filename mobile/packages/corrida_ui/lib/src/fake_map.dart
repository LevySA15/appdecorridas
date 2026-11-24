import 'dart:math' as math;

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'theme.dart';

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
Offset offsetFromPlace(Place place, Size size) {
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

/// Onde o quadrado da cidade começa dentro de uma área maior (o quadrado fica centralizado; fora dele o desenho
/// da cidade continua, mas toque ali vale como a borda).
Offset _origin(Size size) => Offset(
  (size.width - size.shortestSide) / 2,
  (size.height - size.shortestSide) / 2,
);

Place _placeFromLocal(Offset local, Size size) {
  final square = Size.square(size.shortestSide);
  final inside = local - _origin(size);
  return pointFromTap(
    Offset(
      inside.dx.clamp(0.0, square.width),
      inside.dy.clamp(0.0, square.height),
    ),
    square,
  );
}

Offset _localFromPlace(Place place, Size size) =>
    _origin(size) + offsetFromPlace(place, Size.square(size.shortestSide));

/// Desenho esquemático da cidade de mentira: o primeiro toque marca a origem, o segundo marca o destino; tocar
/// de novo depois dos dois só substitui o destino.
class FakeMapPicker extends StatefulWidget {
  const FakeMapPicker({required this.onChanged, this.pickup, super.key});

  final void Function(Place? pickup, Place? destination) onChanged;

  /// Quando muda para um ponto novo, ele vira o embarque (e o destino marcado antes sai).
  final Place? pickup;

  @override
  State<FakeMapPicker> createState() => _FakeMapPickerState();
}

class _FakeMapPickerState extends State<FakeMapPicker> {
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
  void didUpdateWidget(covariant FakeMapPicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    final novo = widget.pickup;
    if (novo != null && novo != oldWidget.pickup) {
      setState(() {
        _pickup = novo;
        _destination = null;
      });
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => widget.onChanged(_pickup, _destination),
      );
    }
  }

  void _handleTapDown(TapDownDetails details, Size size) {
    final point = _placeFromLocal(details.localPosition, size);
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
    final dark = Theme.of(context).brightness == Brightness.dark;
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: (details) => _handleTapDown(details, size),
          child: CustomPaint(
            size: size,
            painter: _CityPainter(
              dark: dark,
              markers: [
                if (_pickup != null) MapMarker(MarkerKind.pickup, _pickup!),
                if (_destination != null)
                  MapMarker(MarkerKind.destination, _destination!),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Quem aparece no mapa de ver: o próprio motoqueiro, o embarque e o destino.
enum MarkerKind { me, pickup, destination }

class MapMarker {
  const MapMarker(this.kind, this.place);

  final MarkerKind kind;
  final Place place;

  @override
  bool operator ==(Object other) =>
      other is MapMarker && other.kind == kind && other.place == place;

  @override
  int get hashCode => Object.hash(kind, place);
}

/// Mapa de mentira sem escolha de origem/destino: desenha os marcadores e, se [onTap] existir, devolve
/// o ponto tocado (é assim que o motoqueiro "anda" enquanto não há GPS).
class FakeMapView extends StatelessWidget {
  const FakeMapView({required this.markers, this.onTap, super.key});

  final List<MapMarker> markers;
  final ValueChanged<Place>? onTap;

  @override
  Widget build(BuildContext context) {
    final onTapAtual = onTap;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: onTapAtual == null
              ? null
              : (details) =>
                    onTapAtual(_placeFromLocal(details.localPosition, size)),
          child: CustomPaint(
            size: size,
            painter: _CityPainter(dark: dark, markers: markers),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Desenho: ruas, quarteirões e praças (sempre o mesmo para a mesma cidade) e os pinos por cima.

class _CityPainter extends CustomPainter {
  _CityPainter({required this.dark, required this.markers});

  final bool dark;
  final List<MapMarker> markers;

  Color get _land => dark ? const Color(0xFF10151C) : const Color(0xFFEDEFF2);
  Color get _road => dark ? const Color(0xFF222B38) : const Color(0xFFFFFFFF);
  Color get _park => dark ? const Color(0xFF13251D) : const Color(0xFFD6E8D4);
  Color get _water => dark ? const Color(0xFF0E2433) : const Color(0xFFCFE3F2);

  // ruas a cada ~700 m (com um tremido para não parecer tabuleiro) e uma avenida a cada 4
  static const _pitchM = 700.0;

  /// Um número estável entre 0 e 1 para a rua `line` (o mesmo desenho sempre).
  double _jitter(int line, int axis) {
    final x = math.sin(line * 12.9898 + axis * 78.233) * 43758.5453;
    return x - x.floorToDouble();
  }

  @override
  void paint(Canvas canvas, Size size) {
    canvas.clipRect(Offset.zero & size);
    final side = size.shortestSide;
    final origin = _origin(size);
    final k = side / (2 * fakeMapHalfSizeM); // pixels por metro
    final pitch = _pitchM * k;

    canvas.drawRect(Offset.zero & size, Paint()..color = _land);

    // praças e parques: manchas verdes em lugares fixos
    final parkPaint = Paint()..color = _park;
    for (var i = -6; i <= 6; i++) {
      for (var j = -6; j <= 6; j++) {
        final r = _jitter(i * 31 + j, j + 3);
        if (r < 0.93) continue;
        final c =
            origin +
            Offset(side / 2 + i * 3.1 * pitch, side / 2 + j * 2.7 * pitch);
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(center: c, width: pitch * 1.5, height: pitch * 1.1),
            const Radius.circular(10),
          ),
          parkPaint,
        );
      }
    }

    // o rio: uma curva larga atravessando a cidade
    final river = Path()
      ..moveTo(origin.dx - side * 0.2, origin.dy + side * 0.82)
      ..cubicTo(
        origin.dx + side * 0.25,
        origin.dy + side * 0.55,
        origin.dx + side * 0.55,
        origin.dy + side * 0.95,
        origin.dx + side * 1.2,
        origin.dy + side * 0.62,
      );
    canvas.drawPath(
      river,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = math.max(14 * k * 6, 14)
        ..strokeCap = StrokeCap.round
        ..color = _water,
    );

    // ruas: linhas retas com o tremido; a cada 3ª é avenida
    final minI = ((0 - origin.dx) / pitch).floor() - 1;
    final maxI = ((size.width - origin.dx) / pitch).ceil() + 1;
    final minJ = ((0 - origin.dy) / pitch).floor() - 1;
    final maxJ = ((size.height - origin.dy) / pitch).ceil() + 1;
    Paint stroke(bool avenue) => Paint()
      ..color = _road
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = avenue ? 7 : 3;
    for (var i = minI; i <= maxI; i++) {
      final x = origin.dx + (i + (_jitter(i, 1) - 0.5) * 0.45) * pitch;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), stroke(i % 3 == 0));
    }
    for (var j = minJ; j <= maxJ; j++) {
      final y = origin.dy + (j + (_jitter(j, 2) - 0.5) * 0.45) * pitch;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), stroke(j % 3 == 0));
    }
    // duas diagonais cortando o tabuleiro
    final diagonal = stroke(true);
    canvas.drawLine(
      origin + Offset(-side * 0.1, side * 0.2),
      origin + Offset(side * 1.1, side * 0.75),
      diagonal,
    );
    canvas.drawLine(
      origin + Offset(side * 0.15, side * 1.1),
      origin + Offset(side * 0.8, -side * 0.1),
      diagonal,
    );

    // a borda da área que o servidor cobre
    final area = Rect.fromLTWH(origin.dx, origin.dy, side, side);
    canvas.drawRect(
      area,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = (dark ? Colors.white : Colors.black).withValues(alpha: 0.10),
    );

    // praça do centro
    final center = area.center;
    canvas.drawCircle(center, 7, Paint()..color = _road);
    canvas.drawCircle(center, 4, Paint()..color = _park);

    // o trajeto: do embarque ao destino
    MapMarker? pickup;
    MapMarker? destination;
    for (final marker in markers) {
      if (marker.kind == MarkerKind.pickup) pickup = marker;
      if (marker.kind == MarkerKind.destination) destination = marker;
    }
    if (pickup != null && destination != null) {
      final a = _localFromPlace(pickup.place, size);
      final b = _localFromPlace(destination.place, size);
      canvas.drawLine(
        a,
        b,
        Paint()
          ..color = dark ? const Color(0xFF0C0F14) : Colors.white
          ..strokeWidth = 9
          ..strokeCap = StrokeCap.round,
      );
      canvas.drawLine(
        a,
        b,
        Paint()
          ..color = corridaAccent
          ..strokeWidth = 5
          ..strokeCap = StrokeCap.round,
      );
    }

    for (final marker in markers) {
      _drawMarker(canvas, marker.kind, _localFromPlace(marker.place, size));
    }
  }

  void _drawMarker(Canvas canvas, MarkerKind kind, Offset at) {
    final ring = Paint()..color = dark ? const Color(0xFF0C0F14) : Colors.white;
    final shadow = Paint()
      ..color = Colors.black.withValues(alpha: 0.25)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3);
    switch (kind) {
      case MarkerKind.pickup:
        canvas.drawCircle(at + const Offset(0, 2), 11, shadow);
        canvas.drawCircle(at, 11, ring);
        canvas.drawCircle(at, 7, Paint()..color = corridaAccent);
      case MarkerKind.destination:
        final square = Rect.fromCenter(center: at, width: 22, height: 22);
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            square.shift(const Offset(0, 2)),
            const Radius.circular(6),
          ),
          shadow,
        );
        canvas.drawRRect(
          RRect.fromRectAndRadius(square, const Radius.circular(6)),
          ring,
        );
        canvas.drawRRect(
          RRect.fromRectAndRadius(square.deflate(4), const Radius.circular(3)),
          Paint()..color = dark ? Colors.white : const Color(0xFF14161A),
        );
      case MarkerKind.me:
        canvas.drawCircle(at + const Offset(0, 2), 16, shadow);
        canvas.drawCircle(at, 16, ring);
        canvas.drawCircle(
          at,
          13,
          Paint()..color = dark ? Colors.white : const Color(0xFF14161A),
        );
        final icon = Icons.two_wheeler_rounded;
        final text = TextPainter(
          text: TextSpan(
            text: String.fromCharCode(icon.codePoint),
            style: TextStyle(
              fontFamily: icon.fontFamily,
              package: icon.fontPackage,
              fontSize: 17,
              color: dark ? const Color(0xFF14161A) : Colors.white,
            ),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        text.paint(canvas, at - Offset(text.width / 2, text.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant _CityPainter oldDelegate) =>
      oldDelegate.dark != dark || !_sameMarkers(oldDelegate.markers, markers);

  bool _sameMarkers(List<MapMarker> a, List<MapMarker> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}
