"""Tempo de chegada falso: linha reta a velocidade constante. Para testes e para o simulador."""
from __future__ import annotations

from app.domain.geo import GeoPoint, haversine_m


class StraightLineEta:
    def __init__(self, speed_mps: float = 8.0) -> None:
        # 8 m/s ≈ 29 km/h, uma velocidade plausível para moto na cidade.
        self.speed_mps = speed_mps

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        return int(haversine_m(origin, destination) / self.speed_mps)
