"""Distâncias geográficas simples (sem bibliotecas externas)."""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


def haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def distance_to_segment_m(p: GeoPoint, a: GeoPoint, b: GeoPoint) -> float:
    """Menor distância de `p` ao segmento a–b, em metros (projeção local plana)."""
    lat0 = math.radians(p.lat)

    def to_xy(q: GeoPoint) -> tuple[float, float]:
        x = math.radians(q.lng - p.lng) * math.cos(lat0) * EARTH_RADIUS_M
        y = math.radians(q.lat - p.lat) * EARTH_RADIUS_M
        return x, y

    ax, ay = to_xy(a)
    bx, by = to_xy(b)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / seg_len2))
    return math.hypot(ax + t * dx, ay + t * dy)


def distance_to_route_m(p: GeoPoint, route: list[GeoPoint]) -> float:
    if not route:
        raise ValueError("a rota está vazia")
    if len(route) == 1:
        return haversine_m(p, route[0])
    return min(distance_to_segment_m(p, a, b) for a, b in zip(route, route[1:]))
