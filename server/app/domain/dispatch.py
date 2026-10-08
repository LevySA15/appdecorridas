"""Escolha da moto e reserva (spec, seção 5). Sem rede: o tempo de rota vem de um EtaProvider."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.domain.config import DispatchConfig
from app.domain.geo import GeoPoint, haversine_m

_DEFAULT = DispatchConfig()


class EtaProvider(Protocol):
    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int: ...


@dataclass
class RiderStatus:
    rider_id: str
    position: GeoPoint
    online: bool = True
    active_ride_id: str | None = None
    queued_ride_id: str | None = None
    seconds_to_finish: int | None = None
    finish_point: GeoPoint | None = None


@dataclass(frozen=True)
class Candidate:
    rider_id: str
    eta_seconds: int
    will_queue: bool


def is_finishing(r: RiderStatus, cfg: DispatchConfig = _DEFAULT) -> bool:
    """A moto tem corrida ativa, mas está acabando: perto do tempo ou perto do destino."""
    if r.active_ride_id is None:
        return False
    if r.seconds_to_finish is not None and r.seconds_to_finish <= cfg.finishing_max_s:
        return True
    if r.finish_point is not None and haversine_m(r.position, r.finish_point) <= cfg.finishing_max_m:
        return True
    return False


def is_eligible(r: RiderStatus, cfg: DispatchConfig = _DEFAULT) -> bool:
    if not r.online or r.queued_ride_id is not None:
        return False
    if r.active_ride_id is None:
        return True
    return is_finishing(r, cfg)


def _origin(r: RiderStatus) -> GeoPoint:
    """De onde a moto sai para buscar o passageiro: do fim da corrida atual, se houver."""
    if r.active_ride_id is not None and r.finish_point is not None:
        return r.finish_point
    return r.position


def rank_candidates(
    riders: Sequence[RiderStatus],
    pickup: GeoPoint,
    eta: EtaProvider,
    cfg: DispatchConfig = _DEFAULT,
) -> list[Candidate]:
    """Motos elegíveis, ordenadas pelo tempo total até o passageiro.

    A rota só é calculada para as `max_candidates_routed` motos mais próximas em linha reta
    (economiza o custo de mapas).
    """
    eligible = [r for r in riders if is_eligible(r, cfg)]
    eligible.sort(key=lambda r: haversine_m(_origin(r), pickup))
    candidates: list[Candidate] = []
    for r in eligible[: cfg.max_candidates_routed]:
        busy = r.active_ride_id is not None
        wait = (r.seconds_to_finish or 0) if busy else 0
        candidates.append(Candidate(r.rider_id, wait + eta.eta_seconds(_origin(r), pickup), busy))
    candidates.sort(key=lambda c: c.eta_seconds)
    return candidates


def next_offer(candidates: list[Candidate], declined: set[str]) -> Candidate | None:
    for c in candidates:
        if c.rider_id not in declined:
            return c
    return None


class ReservationBook:
    """Garante que uma moto recebe a oferta de um pedido só de cada vez (nunca dois ao mesmo tempo)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_rider: dict[str, str] = {}

    def reserve(self, rider_id: str, ride_id: str) -> bool:
        with self._lock:
            current = self._by_rider.get(rider_id)
            if current is not None and current != ride_id:
                return False
            self._by_rider[rider_id] = ride_id
            return True

    def release(self, rider_id: str, ride_id: str) -> None:
        with self._lock:
            if self._by_rider.get(rider_id) == ride_id:
                del self._by_rider[rider_id]
