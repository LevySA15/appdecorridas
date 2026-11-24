import 'dart:math' as math;

import 'package:corrida_core/corrida_core.dart';

import 'fake_map.dart' show MapMarker, MarkerKind;

/// Até onde as pontas do traçado podem ficar do embarque e do destino marcados (o traçado do Google "gruda" na rua mais
/// perto, então difere do ponto tocado em alguns metros). Mais que isso é um traçado de outro pedido: vale a linha reta.
const routeEndSlackM = 500.0;

double _metersBetween(Place a, Place b) {
  const radius = 6371000.0;
  double rad(double degrees) => degrees * math.pi / 180;
  final dLat = rad(b.lat - a.lat);
  final dLng = rad(b.lng - a.lng);
  final h =
      math.pow(math.sin(dLat / 2), 2) +
      math.cos(rad(a.lat)) *
          math.cos(rad(b.lat)) *
          math.pow(math.sin(dLng / 2), 2);
  return 2 * radius * math.asin(math.sqrt(h.toDouble()));
}

/// O traçado pelas ruas, se ele combina com o embarque e o destino marcados (as pontas perto dos dois); senão lista vazia
/// (traçado de outro pedido, ou o servidor sem o mapa do Google, que manda só os dois pontos).
List<Place> usableRoute(Place pickup, Place destination, List<Place> route) =>
    route.length >= 2 &&
        _metersBetween(route.first, pickup) <= routeEndSlackM &&
        _metersBetween(route.last, destination) <= routeEndSlackM
    ? route
    : const [];

/// Os pontos da linha entre embarque e destino: o traçado pelas ruas ([route]) quando ele combina com os dois pontos, senão
/// a linha reta entre eles (sem o mapa do Google no servidor, ou traçado velho de uma cotação anterior).
List<Place> routeLine(
  Place pickup,
  Place destination, [
  List<Place> route = const [],
]) {
  final streets = usableRoute(pickup, destination, route);
  return streets.isEmpty ? [pickup, destination] : streets;
}

/// Embarque e destino dos [markers], ou `null` se falta algum dos dois (sem os dois não há linha).
({Place pickup, Place destination})? tripEnds(List<MapMarker> markers) {
  Place? pickup;
  Place? destination;
  for (final marker in markers) {
    if (marker.kind == MarkerKind.pickup) pickup = marker.place;
    if (marker.kind == MarkerKind.destination) destination = marker.place;
  }
  if (pickup == null || destination == null) return null;
  return (pickup: pickup, destination: destination);
}

/// Tudo o que a câmera precisa enquadrar: os marcadores e, se houver traçado que combine, as curvas dele (a rua pode sair
/// do retângulo entre embarque e destino).
List<Place> placesToFrame(List<MapMarker> markers, List<Place> route) {
  final ends = tripEnds(markers);
  final streets = ends == null
      ? const <Place>[]
      : usableRoute(ends.pickup, ends.destination, route);
  return [for (final marker in markers) marker.place, ...streets];
}
