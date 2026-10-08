"""Preço da corrida (spec, seção 6). Valores em centavos inteiros."""
from __future__ import annotations

import math

from app.domain.config import PricingConfig

_DEFAULT = PricingConfig()


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _clamp_factor(factor: float, cfg: PricingConfig) -> float:
    return max(cfg.factor_min, min(cfg.factor_max, factor))


def distance_fare_cents(distance_m: float, cfg: PricingConfig = _DEFAULT) -> int:
    if distance_m < 0:
        raise ValueError("a distância não pode ser negativa")
    return cfg.base_fare_cents + _round_half_up(cfg.per_km_cents * distance_m / 1000)


def target_factor(pending_requests: int, free_riders: int, cfg: PricingConfig = _DEFAULT) -> float:
    """Fator desejado: relação entre pedidos e motos livres, limitada à faixa da config."""
    if pending_requests < 0 or free_riders < 0:
        raise ValueError("pedidos e motos não podem ser negativos")
    ratio = (pending_requests + 1) / (free_riders + 1)
    return _clamp_factor(ratio, cfg)


def smooth_factor(previous: float, target: float, cfg: PricingConfig = _DEFAULT) -> float:
    """Anda do fator anterior para o alvo em passos de no máximo `max_factor_step`."""
    delta = target - previous
    if abs(delta) <= cfg.max_factor_step:
        return target
    return previous + math.copysign(cfg.max_factor_step, delta)


def final_price_cents(distance_m: float, factor: float, cfg: PricingConfig = _DEFAULT) -> int:
    raw = distance_fare_cents(distance_m, cfg) * _clamp_factor(factor, cfg)
    rounded = _round_half_up(raw / cfg.round_to_cents) * cfg.round_to_cents
    return max(cfg.min_price_cents, rounded)


def price_reason(factor: float) -> str:
    if factor <= 0.9:
        return "Muita moto livre agora, preço menor."
    if factor >= 1.2:
        return "Poucas motos agora, preço maior."
    return "Preço normal para este horário."
