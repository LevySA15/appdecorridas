"""Tempo de chegada falso: linha reta a velocidade constante. Para testes e para o simulador."""
from __future__ import annotations

from app.domain.geo import GeoPoint, haversine_m
from app.domain.maps import Route


class StraightLineEta:
    def __init__(self, speed_mps: float = 8.0) -> None:
        # 8 m/s ≈ 29 km/h, uma velocidade plausível para moto na cidade.
        self.speed_mps = speed_mps

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        return int(haversine_m(origin, destination) / self.speed_mps)


class FakeMaps(StraightLineEta):
    """Mapa falso: a rua é 30% mais longa que a linha reta e a rota é um segmento só. Sem endereço escrito: inventar
    rua num recibo seria pior do que deixar em branco."""

    def describe(self, point: GeoPoint) -> str | None:
        return None

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        distance = haversine_m(origin, destination) * 1.3
        return Route(
            distance_m=int(round(distance)),
            duration_s=int(distance / self.speed_mps),
            points=(origin, destination),
        )


class StreetGridMaps(FakeMaps):
    """Mapa falso com "ruas em escada", só para **demonstração** (navegador, vídeos): a rota anda para o norte/sul e para
    leste/oeste em degraus, como uma cidade em quadras, em vez de uma reta. Assim dá para ver o app desenhar um traçado
    de verdade sem a chave do Google. Liga com `FAKE_MAPS_STREETS=on`; nunca em produção (a distância muda)."""

    STEPS = 3

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        points = [origin]
        for step in range(self.STEPS):
            lat = origin.lat + (destination.lat - origin.lat) * (step + 1) / self.STEPS
            lng_to = origin.lng + (destination.lng - origin.lng) * (step + 1) / self.STEPS
            points.append(GeoPoint(lat, points[-1].lng))      # anda na vertical...
            points.append(GeoPoint(lat, lng_to))              # ...e depois na horizontal
        distance = sum(haversine_m(a, b) for a, b in zip(points, points[1:]))
        return Route(
            distance_m=int(round(distance)), duration_s=int(distance / self.speed_mps), points=tuple(points),
        )
