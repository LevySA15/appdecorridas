"""Rastro curto de posições da corrida em andamento, rota esperada e controle de avisos repetidos.

Fica no Redis porque muda a cada 4 segundos e só importa durante a corrida. Se o Redis for esvaziado
no meio da corrida, a rota é lida de novo do banco e o rastro recomeça: a pior consequência é demorar
alguns minutos para o próximo aviso.
"""
from __future__ import annotations

import json
from typing import Protocol

import redis

from app.domain.geo import GeoPoint
from app.domain.safety import PositionSample

_TTL_S = 6 * 3600       # uma corrida não passa disso; depois o Redis limpa sozinho


class SafetyStore(Protocol):
    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        """Acrescenta a posição e devolve as últimas `max_samples`, da mais antiga à mais nova."""

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        """A rota esperada, `[]` se a corrida não tem rota guardada, ou None se ainda não foi carregada."""

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None: ...

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        """True se ninguém pegou `key` nos últimos `cooldown_s` segundos (e passa a valer como pegada agora)."""


class InMemorySafetyStore:
    def __init__(self) -> None:
        self._samples: dict[str, list[PositionSample]] = {}
        self._routes: dict[str, list[GeoPoint]] = {}
        self._claims: dict[str, float] = {}

    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        samples = self._samples.setdefault(ride_id, [])
        samples.append(sample)
        del samples[:-max_samples]
        return list(samples)

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        return self._routes.get(ride_id)

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None:
        self._routes[ride_id] = list(route)

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        until = self._claims.get(key)
        if until is not None and now < until:
            return False
        self._claims[key] = now + cooldown_s
        return True


# Pegar o aviso numa ida só ao Redis: com GET e SET separados, dois pedidos ao mesmo tempo avisariam duas vezes.
_CLAIM_LUA = """
local blocked_until = redis.call('get', KEYS[1])
if blocked_until and tonumber(ARGV[1]) < tonumber(blocked_until) then return 0 end
redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class RedisSafetyStore:
    def __init__(self, client: redis.Redis, prefix: str = "safety:") -> None:
        if not client.connection_pool.connection_kwargs.get("decode_responses"):
            raise ValueError("o cliente Redis precisa ser criado com decode_responses=True")
        self.r = client
        self.prefix = prefix
        self._claim = client.register_script(_CLAIM_LUA)

    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        key = f"{self.prefix}s:{ride_id}"
        pipe = self.r.pipeline()
        pipe.rpush(key, f"{sample.t!r},{sample.point.lat!r},{sample.point.lng!r}")
        pipe.ltrim(key, -max_samples, -1)
        pipe.expire(key, _TTL_S)
        pipe.lrange(key, 0, -1)
        raw = pipe.execute()[-1]
        samples = []
        for item in raw:
            t, lat, lng = item.split(",")
            samples.append(PositionSample(GeoPoint(float(lat), float(lng)), float(t)))
        return samples

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        raw = self.r.get(f"{self.prefix}r:{ride_id}")
        if raw is None:
            return None
        return [GeoPoint(lat, lng) for lat, lng in json.loads(raw)]

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None:
        self.r.set(f"{self.prefix}r:{ride_id}", json.dumps([[p.lat, p.lng] for p in route]), ex=_TTL_S)

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        return bool(
            self._claim(keys=[f"{self.prefix}c:{key}"], args=[repr(now), repr(now + cooldown_s), int(cooldown_s) + 60])
        )
