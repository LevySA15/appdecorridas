"""Todos os números ajustáveis do sistema. Valores em centavos, segundos ou metros.

Os padrões abaixo vêm da spec (seções 2, 5, 6, 7, 9) ou são propostas iniciais que o Levy
ajusta com dados reais. Nada aqui é lido de arquivo ainda: o servidor da etapa seguinte
vai carregar estes valores do banco.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingConfig:
    base_fare_cents: int = 300      # bandeirada
    per_km_cents: int = 150         # por quilômetro
    min_price_cents: int = 500      # piso: R$ 5,00
    round_to_cents: int = 50        # arredonda para R$ 0,50
    factor_min: float = 0.8
    factor_max: float = 1.6
    max_factor_step: float = 0.1    # mudança máxima do fator por atualização


@dataclass(frozen=True)
class FeeTier:
    from_ride: int                  # número da corrida do dia (começa em 1)
    to_ride: int | None             # None = faixa aberta (última)
    fee_cents: int


@dataclass(frozen=True)
class FeeConfig:
    tiers: tuple[FeeTier, ...] = (FeeTier(1, 5, 100), FeeTier(6, 10, 90), FeeTier(11, None, 80))
    min_fee_cents: int = 70             # piso de lucro: Pix R$ 0,50 + mapas ~R$ 0,19
    trial_rides: int = 10               # corridas antes de pagar a entrada
    entry_fee_cents: int = 5000         # R$ 50, uma vez só
    cash_debt_limit_cents: int = 1000   # R$ 10 de dívida de corridas em dinheiro
    max_debt_share: float = 0.5         # no máximo 50% do ganho da corrida Pix abate dívida


@dataclass(frozen=True)
class RideConfig:
    pix_window_s: int = 120
    free_cancel_after_accept_s: int = 60
    cancel_compensation_cents: int = 200
    max_wait_at_arrival_s: int = 300
    queue_max_wait_s: int = 480
    search_give_up_s: int = 120


@dataclass(frozen=True)
class DispatchConfig:
    offer_timeout_s: int = 15
    max_candidates_routed: int = 3
    finishing_max_s: int = 120
    finishing_max_m: int = 500


@dataclass(frozen=True)
class SafetyConfig:
    stopped_after_s: int = 180
    stopped_radius_m: float = 30.0
    off_route_m: float = 300.0
    off_route_confirmations: int = 3
    max_plausible_speed_kmh: float = 140.0
    reanchor_after_rejects: int = 3
    mock_location_jumps: int = 2
