"""Divisão do pagamento, eventos repetidos do provedor e interface do provedor (spec, seção 7)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.config import FeeConfig
from app.domain.fees import RiderAccount

_DEFAULT_DEBT_SHARE = FeeConfig().max_debt_share


@dataclass(frozen=True)
class Split:
    rider_cents: int
    company_cents: int
    debt_paid_cents: int


def compute_split(
    price_cents: int,
    fee_cents: int,
    debt_cents: int = 0,
    max_debt_share: float = _DEFAULT_DEBT_SHARE,
) -> Split:
    """Divide o preço entre motoqueiro e empresa.

    A empresa fica com a taxa mais o que for abatido da dívida de corridas em dinheiro.
    O abatimento é limitado a `max_debt_share` do que o motoqueiro receberia.
    """
    if price_cents <= 0 or fee_cents < 0 or debt_cents < 0:
        raise ValueError("preço, taxa e dívida precisam ser positivos")
    if fee_cents > price_cents:
        raise ValueError("a taxa é maior que o preço da corrida")
    rider_gross = price_cents - fee_cents
    debt_paid = min(debt_cents, int(rider_gross * max_debt_share))
    return Split(
        rider_cents=rider_gross - debt_paid,
        company_cents=fee_cents + debt_paid,
        debt_paid_cents=debt_paid,
    )


def settle_pix_ride(
    acc: RiderAccount,
    price_cents: int,
    fee_cents: int,
    max_debt_share: float = _DEFAULT_DEBT_SHARE,
) -> Split:
    """Calcula a divisão de uma corrida Pix e abate a dívida da conta do motoqueiro."""
    split = compute_split(price_cents, fee_cents, acc.cash_debt_cents, max_debt_share)
    acc.cash_debt_cents -= split.debt_paid_cents
    return split


class ProcessedEvents:
    """Guarda os avisos do provedor já tratados, para nunca tratar o mesmo aviso duas vezes."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def first_time(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


@dataclass
class PixCharge:
    charge_id: str
    ride_id: str
    rider_id: str
    amount_cents: int
    split: Split
    paid: bool = False
    refunded: bool = False


class PaymentProvider(Protocol):
    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split
    ) -> PixCharge: ...

    def refund(self, charge_id: str) -> None: ...
