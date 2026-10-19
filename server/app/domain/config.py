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
    factor_interval_s: float = 30.0 # tempo mínimo entre duas atualizações do fator (o preço muda aos poucos)


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
    free_cancel_after_accept_s: int = 300   # janela grátis de cancelamento, contada do aceite da moto
    cancel_fee_min_cents: int = 300         # taxa de cancelamento tardio: R$ 3,00 com a moto saindo...
    cancel_fee_max_cents: int = 500         # ...a R$ 5,00 com a moto no ponto de embarque
    cancel_fee_round_cents: int = 10        # a taxa é arredondada a R$ 0,10
    appeal_window_s: int = 7 * 86_400       # prazo para o passageiro pedir revisão da taxa
    max_wait_at_arrival_s: int = 300
    queue_max_wait_s: int = 480
    search_give_up_s: int = 120
    cash_pay_wait_s: int = 300      # espera pelo pagamento do fim da corrida em dinheiro
    quote_ttl_s: int = 300          # validade do preço mostrado antes do pedido
    min_trip_m: int = 100           # origem e destino mais perto que isso não é corrida
    max_trip_m: int = 40_000        # em linha reta; mais longe que isso não é corrida de moto na cidade


@dataclass(frozen=True)
class DispatchConfig:
    offer_timeout_s: int = 15
    max_candidates_routed: int = 3
    finishing_max_s: int = 120
    finishing_max_m: int = 500
    search_radius_m: float = 3000.0     # só motos até essa distância em linha reta recebem oferta
    position_max_age_s: float = 30.0    # posição mais velha que isso não conta


@dataclass(frozen=True)
class SafetyConfig:
    stopped_after_s: int = 180
    stopped_radius_m: float = 30.0
    off_route_m: float = 300.0
    off_route_confirmations: int = 3
    max_plausible_speed_kmh: float = 140.0
    reanchor_after_rejects: int = 3
    mock_location_jumps: int = 2
    alert_cooldown_s: int = 600     # depois de um aviso, o mesmo tipo de aviso não repete nesse tempo
    # "muito tempo sem sinal": tabela provisória do Levy (19/10/2026); depois vira um algoritmo de distância
    no_signal_short_m: int = 3000   # corrida até 3 km...
    no_signal_long_m: int = 10_000  # ...de 3 a 10 km... (acima disso, a faixa longa)
    no_signal_short_s: int = 120    # ...2 minutos sem sinal
    no_signal_mid_s: int = 240      # ...4 minutos
    no_signal_long_s: int = 360     # ...6 minutos
    max_samples: int = 120          # posições guardadas por corrida (cerca de 8 minutos a cada 4 s)


@dataclass(frozen=True)
class BalanceConfig:
    """Saldo do passageiro. A recarga fica desligada até o advogado responder (spec, seção 7.5)."""

    topup_enabled: bool = False
    topup_min_cents: int = 1000
    topup_max_cents: int = 20_000


@dataclass(frozen=True)
class AuthConfig:
    otp_digits: int = 6
    otp_ttl_s: int = 300
    otp_max_attempts: int = 5
    otp_requests_per_hour: int = 5
    otp_requests_per_ip_hour: int = 100   # por aparelho/rede; alto porque várias pessoas dividem o mesmo IP no 4G
    session_days: int = 180


def validate_ride_config(cfg: RideConfig) -> None:
    """Confere os números do cancelamento tardio e do recurso."""
    if cfg.cancel_fee_min_cents <= 0 or cfg.cancel_fee_max_cents < cfg.cancel_fee_min_cents:
        raise ValueError("a taxa de cancelamento precisa ser positiva e o mínimo não pode passar do máximo")
    if cfg.cancel_fee_round_cents <= 0:
        raise ValueError("o arredondamento da taxa de cancelamento precisa ser positivo")
    if cfg.appeal_window_s <= 0:
        raise ValueError("o prazo do recurso precisa ser positivo")


def validate_balance_config(cfg: BalanceConfig) -> None:
    """Confere os limites da recarga de saldo."""
    if cfg.topup_min_cents <= 0 or cfg.topup_max_cents < cfg.topup_min_cents:
        raise ValueError("os limites da recarga precisam ser positivos, com o mínimo não maior que o máximo")
