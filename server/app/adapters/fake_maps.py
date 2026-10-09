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
    """Mapa falso: a rua é 30% mais longa que a linha reta e a rota é um segmento só."""

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        distance = haversine_m(origin, destination) * 1.3
        return Route(
            distance_m=int(round(distance)),
            duration_s=int(distance / self.speed_mps),
            points=(origin, destination),
        )
