"""Tipos de mapa que o resto do sistema usa. O Google Maps (plano 7) e o mapa falso cumprem este contrato."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.geo import GeoPoint


@dataclass(frozen=True)
class Route:
    distance_m: int
    duration_s: int
    points: tuple[GeoPoint, ...]


class MapsProvider(Protocol):
    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route: ...

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int: ...
