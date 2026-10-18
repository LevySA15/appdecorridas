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

    def prune(self, now: float, max_age_s: float) -> int:
        """Esquece quem não manda posição há mais de `max_age_s` (celular desligado, app fechado)."""
        ...


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

    def prune(self, now: float, max_age_s: float) -> int:
        gone = [rider_id for rider_id, seen in self._seen.items() if now - seen > max_age_s]
        for rider_id in gone:
            self.remove(rider_id)
        return len(gone)

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


# Tirar quem sumiu numa ida só: lendo e apagando em comandos separados, uma posição nova que chegasse
# no meio seria apagada junto.
_PRUNE_LUA = """
local old = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1])
for _, id in ipairs(old) do
    redis.call('zrem', KEYS[1], id)
    redis.call('zrem', KEYS[2], id)
end
return #old
"""


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
        self._prune = client.register_script(_PRUNE_LUA)

    def prune(self, now: float, max_age_s: float) -> int:
        return int(self._prune(keys=[self.GEO, self.SEEN], args=[repr(now - max_age_s)]))

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


class FactorStore(Protocol):
    def get(self) -> tuple[float, float] | None:
        """(fator, instante da última atualização), ou None se nunca houve."""

    def set(self, value: float, updated_at: float) -> None: ...


class InMemoryFactorStore:
    def __init__(self) -> None:
        self._state: tuple[float, float] | None = None

    def get(self) -> tuple[float, float] | None:
        return self._state

    def set(self, value: float, updated_at: float) -> None:
        self._state = (value, updated_at)


class RedisFactorStore:
    """Fator de preço atual e quando mudou (o fator anda aos poucos, então precisa lembrar os dois)."""

    def __init__(self, client: redis.Redis, key: str = "price:factor") -> None:
        self.r = client
        self.key = key

    def get(self) -> tuple[float, float] | None:
        raw = self.r.get(self.key)
        if raw is None:
            return None
        value, updated_at = raw.split(":")
        return float(value), float(updated_at)

    def set(self, value: float, updated_at: float) -> None:
        self.r.set(self.key, f"{value!r}:{updated_at!r}")



# --- limite de tentativas, saúde do Pix e marcas de tarefas diárias -------------------------------


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
        """Conta mais uma tentativa em `key`. Devolve False quando passou de `limit` na janela atual."""

    def count(self, key: str, window_s: float, now: float) -> int:
        """Quantas tentativas já foram contadas na janela atual (sem contar mais uma)."""


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}

    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
        bucket = (key, int(now // window_s))
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        return self._counts[bucket] <= limit

    def count(self, key: str, window_s: float, now: float) -> int:
        return self._counts.get((key, int(now // window_s)), 0)


class RedisRateLimiter:
    """Janela fixa por chave. O instante vem de quem chama (`now`), como no resto do servidor."""

    def __init__(self, client: redis.Redis, prefix: str = "rl:") -> None:
        self.r = client
        self.prefix = prefix

    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
        bucket = f"{self.prefix}{key}:{int(now // window_s)}"
        pipe = self.r.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, int(window_s * 2))
        count, _ = pipe.execute()
        return int(count) <= limit

    def count(self, key: str, window_s: float, now: float) -> int:
        return int(self.r.get(f"{self.prefix}{key}:{int(now // window_s)}") or 0)


class PixHealth(Protocol):
    def mark_down(self, now: float, for_s: float) -> None: ...

    def is_down(self, now: float) -> bool: ...


class InMemoryPixHealth:
    def __init__(self) -> None:
        self._down_until = 0.0

    def mark_down(self, now: float, for_s: float) -> None:
        self._down_until = max(self._down_until, now + for_s)

    def is_down(self, now: float) -> bool:
        return now < self._down_until


class RedisPixHealth:
    """O Pix é dado como fora do ar até um instante; passado esse instante, volta a ser tentado."""

    def __init__(self, client: redis.Redis, key: str = "pix:down_until") -> None:
        self.r = client
        self.key = key

    def mark_down(self, now: float, for_s: float) -> None:
        until = max(self._until(), now + for_s)
        self.r.set(self.key, repr(until), ex=int(for_s) + 60)

    def _until(self) -> float:
        raw = self.r.get(self.key)
        return float(raw) if raw is not None else 0.0

    def is_down(self, now: float) -> bool:
        return now < self._until()


class JobMarks(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...


class InMemoryJobMarks:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value


class RedisJobMarks:
    def __init__(self, client: redis.Redis, prefix: str = "job:") -> None:
        self.r = client
        self.prefix = prefix

    def get(self, name: str) -> str | None:
        return self.r.get(f"{self.prefix}{name}")

    def set(self, name: str, value: str) -> None:
        self.r.set(f"{self.prefix}{name}", value)
