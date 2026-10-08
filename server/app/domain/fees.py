"""Taxa por corrida, entrada de R$ 50 e dívida de corridas em dinheiro (spec, seções 2 e 7)."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.config import FeeConfig
from app.domain.types import PaymentMethod

_DEFAULT = FeeConfig()


def validate_fee_config(cfg: FeeConfig) -> None:
    """Confere que as faixas cobrem 1..∞ sem buracos e nenhuma fica abaixo do piso de lucro."""
    if not cfg.tiers:
        raise ValueError("a configuração de taxas não tem faixas")
    expected_start = 1
    for index, tier in enumerate(cfg.tiers):
        if tier.from_ride != expected_start:
            raise ValueError(f"a faixa {index + 1} deveria começar na corrida {expected_start}")
        if tier.fee_cents < cfg.min_fee_cents:
            raise ValueError(f"a faixa {index + 1} está abaixo do piso de lucro")
        if tier.to_ride is None:
            if index != len(cfg.tiers) - 1:
                raise ValueError("só a última faixa pode ser aberta")
            return
        if tier.to_ride < tier.from_ride:
            raise ValueError(f"a faixa {index + 1} termina antes de começar")
        expected_start = tier.to_ride + 1
    raise ValueError("a última faixa precisa ser aberta")


def fee_for_ride(ride_number_today: int, cfg: FeeConfig = _DEFAULT) -> int:
    if ride_number_today < 1:
        raise ValueError("o número da corrida do dia começa em 1")
    for tier in cfg.tiers:
        if ride_number_today >= tier.from_ride and (tier.to_ride is None or ride_number_today <= tier.to_ride):
            return tier.fee_cents
    raise ValueError(f"nenhuma faixa cobre a corrida {ride_number_today}")


@dataclass
class RiderAccount:
    rider_id: str
    completed_rides: int = 0
    entry_paid: bool = False
    cash_debt_cents: int = 0


def offer_block_reason(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> str | None:
    if acc.completed_rides >= cfg.trial_rides and not acc.entry_paid:
        return "entrada_pendente"
    return None


def can_receive_offers(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> bool:
    return offer_block_reason(acc, cfg) is None


def can_receive_cash_offers(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> bool:
    return can_receive_offers(acc, cfg) and acc.cash_debt_cents < cfg.cash_debt_limit_cents


def register_completed_ride(acc: RiderAccount, method: PaymentMethod, fee_cents: int) -> None:
    """Conta a corrida concluída; se foi em dinheiro, a taxa vira dívida do motoqueiro."""
    acc.completed_rides += 1
    if method is PaymentMethod.CASH:
        acc.cash_debt_cents += fee_cents


def mark_entry_paid(acc: RiderAccount) -> None:
    acc.entry_paid = True
