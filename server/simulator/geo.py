"""A cidade de mentira: pontos, distâncias e movimento em linha reta.

As zonas e as ruas são inventadas para a simulação; só o centro é aproximado de Santo Antônio de Jesus.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0
CITY_CENTER: tuple[float, float] = (-12.9644, -39.2597)

Point = tuple[float, float]         # (lat, lng)


def distance_m(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def offset(point: Point, north_m: float, east_m: float) -> Point:
    lat = point[0] + math.degrees(north_m / EARTH_RADIUS_M)
    lng = point[1] + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(point[0]))))
    return (lat, lng)


def move_toward(a: Point, b: Point, meters: float) -> Point:
    """Anda `meters` de `a` em direção a `b` (em linha reta) e para em `b` se passar dele."""
    total = distance_m(a, b)
    if total <= meters or total == 0:
        return b
    t = meters / total
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def midpoint(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def sideways_point(a: Point, b: Point, meters: float) -> Point:
    """O ponto a `meters` de distância, para o lado, do meio do trecho a–b (um desvio de rota)."""
    mid = midpoint(a, b)
    north = (b[0] - a[0]) * 111_320.0
    east = (b[1] - a[1]) * 111_320.0 * math.cos(math.radians(mid[0]))
    norm = math.hypot(north, east) or 1.0
    return offset(mid, -east / norm * meters, north / norm * meters)


@dataclass(frozen=True)
class Zone:
    name: str
    north_m: float
    east_m: float
    radius_m: float
    weight: float


ZONES = (
    Zone("Centro", 0, 0, 500, 4.0),
    Zone("Zona norte", 1400, 200, 450, 1.5),
    Zone("Zona sul", -1500, -100, 450, 1.5),
    Zone("Zona leste", 100, 1600, 450, 1.0),
    Zone("Zona oeste", -200, -1500, 450, 1.0),
)
STREETS = (
    "Rua das Flores", "Rua da Feira", "Avenida Principal", "Rua do Comércio", "Rua São José",
    "Travessa da Paz", "Rua Bahia", "Avenida Central", "Rua das Palmeiras", "Rua do Mercado",
)


@dataclass(frozen=True)
class Place:
    point: Point
    zone: str
    text: str


class City:
    """Sorteia lugares e viagens. `scale` encolhe a cidade (os testes usam uma bem pequena)."""

    def __init__(self, rng: random.Random, scale: float = 1.0, center: Point = CITY_CENTER) -> None:
        self.rng = rng
        self.scale = scale
        self.center = center
        self.min_trip_m = max(150.0, 300.0 * scale)
        self.max_trip_m = 3500.0 * scale if scale < 1 else 3500.0

    def random_place(self, zone: Zone | None = None) -> Place:
        zone = zone or self.rng.choices(ZONES, weights=[z.weight for z in ZONES])[0]
        radius = zone.radius_m * self.scale * math.sqrt(self.rng.random())
        angle = self.rng.uniform(0, 2 * math.pi)
        point = offset(
            self.center,
            zone.north_m * self.scale + radius * math.sin(angle),
            zone.east_m * self.scale + radius * math.cos(angle),
        )
        text = f"{self.rng.choice(STREETS)}, {self.rng.randint(1, 400)} - {zone.name}"
        return Place(point, zone.name, text)

    def random_trip(self) -> tuple[Place, Place]:
        for _ in range(50):
            origin, destination = self.random_place(), self.random_place()
            if self.min_trip_m <= distance_m(origin.point, destination.point) <= self.max_trip_m:
                return origin, destination
        origin = self.random_place()           # cidade minúscula e sorte ruim: destino a uma distância garantida
        point = offset(origin.point, 0, self.min_trip_m * 1.5)
        return origin, Place(point, origin.zone, origin.text)
