"""Alertas de segurança durante a corrida (spec, seção 9). Só vale para corridas em andamento."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.config import SafetyConfig
from app.domain.geo import GeoPoint, distance_to_route_m, haversine_m

_DEFAULT = SafetyConfig()


class AlertType(str, Enum):
    STOPPED = "stopped"
    OFF_ROUTE = "off_route"


@dataclass(frozen=True)
class PositionSample:
    point: GeoPoint
    t: float  # segundos


@dataclass(frozen=True)
class SafetyResult:
    alert: AlertType | None
    suspected_mock_location: bool


def speed_kmh(a: PositionSample, b: PositionSample) -> float:
    dt = b.t - a.t
    if dt <= 0:
        raise ValueError("o tempo precisa avançar entre as amostras")
    return haversine_m(a.point, b.point) / dt * 3.6


def clean_samples(
    samples: list[PositionSample], cfg: SafetyConfig = _DEFAULT
) -> tuple[list[PositionSample], int]:
    """Descarta amostras fora de ordem e saltos impossíveis. Devolve (aceitas, picos isolados).

    Um "pico isolado" é uma ou duas amostras impossíveis seguidas de uma volta à trilha anterior;
    só isso conta para a suspeita de localização falsa. Depois de `reanchor_after_rejects`
    amostras impossíveis seguidas, aceita a nova posição sem contar pico: o sinal pode ter
    voltado em outro lugar, ou a primeira amostra pode ter sido a errada. Um pico que ainda
    não teve desfecho no fim da lista também não conta.
    """
    good: list[PositionSample] = []
    spikes = 0
    pending_rejects = 0
    for s in samples:
        if not good:
            good.append(s)
            continue
        last = good[-1]
        if s.t <= last.t:
            continue
        if speed_kmh(last, s) > cfg.max_plausible_speed_kmh:
            pending_rejects += 1
            if pending_rejects >= cfg.reanchor_after_rejects:
                good.append(s)
                pending_rejects = 0
            continue
        if pending_rejects > 0:
            spikes += 1
        pending_rejects = 0
        good.append(s)
    return good, spikes


def is_stopped_too_long(samples: list[PositionSample], cfg: SafetyConfig = _DEFAULT) -> bool:
    """A moto ficou dentro de `stopped_radius_m` do último ponto por pelo menos `stopped_after_s`."""
    if not samples:
        return False
    last = samples[-1]
    cutoff = last.t - cfg.stopped_after_s
    older = [s for s in samples if s.t <= cutoff]
    if not older:
        return False
    anchor = older[-1]
    recent = [s for s in samples if s.t >= anchor.t]
    return all(haversine_m(s.point, last.point) <= cfg.stopped_radius_m for s in recent)


def is_off_route(
    samples: list[PositionSample], route: list[GeoPoint], cfg: SafetyConfig = _DEFAULT
) -> bool:
    """Confirma antes de avisar: as últimas amostras, todas, estão longe da rota."""
    if len(samples) < cfg.off_route_confirmations:
        return False
    tail = samples[-cfg.off_route_confirmations :]
    return all(distance_to_route_m(s.point, route) > cfg.off_route_m for s in tail)


def evaluate(
    samples: list[PositionSample], route: list[GeoPoint], cfg: SafetyConfig = _DEFAULT
) -> SafetyResult:
    good, jumps = clean_samples(samples, cfg)
    suspected = jumps >= cfg.mock_location_jumps
    if is_stopped_too_long(good, cfg):
        return SafetyResult(AlertType.STOPPED, suspected)
    if is_off_route(good, route, cfg):
        return SafetyResult(AlertType.OFF_ROUTE, suspected)
    return SafetyResult(None, suspected)
