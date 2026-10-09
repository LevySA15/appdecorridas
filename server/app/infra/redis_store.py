"""Posições atuais das motos e reservas de oferta, no Redis (spec, seção 10).

A posição muda a cada poucos segundos, por isso fica no Redis e não no banco principal.
"""
from __future__ import annotations

from typing import Protocol

import redis

from app.domain.geo import GeoPoint, haversine_m


class PositionStore(Protocol):
    def update(self, rider_id: str, point: GeoPoint, now: float) -> None: ...

    def remove(self, rider_id: str) -> None: ...

    def get(self, rider_id: str) -> GeoPoint | None: ...

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]: ...


class InMemoryPositionStore:
    """Versão em memória, para testes e para o simulador."""

    def __init__(self) -> None:
        self._points: dict[str, GeoPoint] = {}
        self._seen: dict[str, float] = {}

    def update(self, rider_id: str, point: GeoPoint, now: float) -> None:
        self._points[rider_id] = point
        self._seen[rider_id] = now

    def remove(self, rider_id: str) -> None:
        self._points.pop(rider_id, None)
        self._seen.pop(rider_id, None)

    def get(self, rider_id: str) -> GeoPoint | None:
        return self._points.get(rider_id)

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]:
        found = [
            (haversine_m(center, point), rider_id, point)
            for rider_id, point in self._points.items()
            if now - self._seen[rider_id] <= max_age_s
        ]
        found = [item for item in found if item[0] <= radius_m]
        found.sort(key=lambda item: item[0])
        return [(rider_id, point) for _, rider_id, point in found]


class RedisPositionStore:
    GEO = "pos:geo"
    SEEN = "pos:seen"

    def __init__(self, client: redis.Redis) -> None:
        if not client.connection_pool.connection_kwargs.get("decode_responses"):
            raise ValueError(
                "o cliente Redis precisa ser criado com decode_responses=True "
                "(senão os ids dos motoqueiros voltam como bytes)"
            )
        self.r = client

    def update(self, rider_id: str, point: GeoPoint, now: float) -> None:
        pipe = self.r.pipeline()
        pipe.geoadd(self.GEO, (point.lng, point.lat, rider_id))
        pipe.zadd(self.SEEN, {rider_id: now})
        pipe.execute()

    def remove(self, rider_id: str) -> None:
        pipe = self.r.pipeline()
        pipe.zrem(self.GEO, rider_id)
        pipe.zrem(self.SEEN, rider_id)
        pipe.execute()

    def get(self, rider_id: str) -> GeoPoint | None:
        pos = self.r.geopos(self.GEO, rider_id)[0]
        if pos is None:
            return None
        return GeoPoint(lat=pos[1], lng=pos[0])

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]:
        found = self.r.geosearch(
            self.GEO,
            longitude=center.lng,
            latitude=center.lat,
            radius=radius_m,
            unit="m",
            sort="ASC",
            withcoord=True,
        )
        if not found:
            return []
        seen = self.r.zmscore(self.SEEN, [item[0] for item in found])
        result: list[tuple[str, GeoPoint]] = []
        for (rider_id, (lng, lat)), ts in zip(found, seen):
            if ts is not None and now - ts <= max_age_s:
                result.append((rider_id, GeoPoint(lat=lat, lng=lng)))
        return result


# Reservar ou renovar numa só ida ao Redis: com GET e PEXPIRE separados, a reserva podia vencer
# no meio e a renovação estender a reserva de outra corrida.
_RESERVE_LUA = """
if redis.call('set', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then return 1 end
if redis.call('get', KEYS[1]) == ARGV[1] then
    redis.call('pexpire', KEYS[1], ARGV[2])
    return 1
end
return 0
"""

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisReservationBook:
    """Reserva de uma moto para a oferta de um pedido só, com validade (`ttl_ms`)."""

    def __init__(self, client: redis.Redis, ttl_ms: int = 30_000, prefix: str = "resv:") -> None:
        self.r = client
        self.ttl_ms = ttl_ms
        self.prefix = prefix
        self._reserve = client.register_script(_RESERVE_LUA)
        self._release = client.register_script(_RELEASE_LUA)

    def _key(self, rider_id: str) -> str:
        return f"{self.prefix}{rider_id}"

    def reserve(self, rider_id: str, ride_id: str) -> bool:
        return bool(self._reserve(keys=[self._key(rider_id)], args=[ride_id, self.ttl_ms]))

    def release(self, rider_id: str, ride_id: str) -> None:
        self._release(keys=[self._key(rider_id)], args=[ride_id])
