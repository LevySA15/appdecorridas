"""Ajudantes de teste: pontos em metros a partir do centro de Santo Antônio de Jesus (aproximado)."""
import math

from app.domain.geo import GeoPoint

ORIGIN = GeoPoint(-12.9644, -39.2597)
_M_PER_DEG_LAT = 111_195.0


def pt(north_m: float = 0.0, east_m: float = 0.0) -> GeoPoint:
    """Ponto a `north_m` metros ao norte e `east_m` metros a leste da origem."""
    lat = ORIGIN.lat + north_m / _M_PER_DEG_LAT
    lng = ORIGIN.lng + east_m / (_M_PER_DEG_LAT * math.cos(math.radians(ORIGIN.lat)))
    return GeoPoint(lat, lng)
