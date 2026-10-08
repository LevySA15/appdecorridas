"""Divisão do pagamento, eventos repetidos do provedor e interface do provedor (spec, seção 7)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


def reserve_pix_split(
    acc: RiderAccount,
    price_cents: int,
    fee_cents: int,
    max_debt_share: float = _DEFAULT_DEBT_SHARE,
) -> Split:
    """Calcula a divisão ao criar a cobrança Pix e RESERVA a parte da dívida que ela vai abater.

    A dívida só diminui quando o Pix é confirmado (`confirm_charge_debt`). Duas cobranças
    pendentes ao mesmo tempo nunca reservam mais do que a dívida existente.
    """
    available = max(0, acc.cash_debt_cents - acc.debt_reserved_cents)
    split = compute_split(price_cents, fee_cents, available, max_debt_share)
    acc.debt_reserved_cents += split.debt_paid_cents
    return split


class DebtState(str, Enum):
    RESERVED = "reserved"  # cobrança criada, Pix ainda não pago
    APPLIED = "applied"    # Pix pago: a dívida foi abatida
    RELEASED = "released"  # Pix venceu ou corrida cancelou antes de pagar: reserva desfeita
    RESTORED = "restored"  # Pix pago foi devolvido: a dívida voltou


def confirm_charge_debt(acc: RiderAccount, charge: PixCharge) -> None:
    """Chegou o aviso de Pix pago: abate a dívida reservada. Repetir o aviso não abate de novo."""
    if charge.debt_state is DebtState.APPLIED:
        return
    if charge.debt_state is not DebtState.RESERVED:
        raise ValueError("a reserva da dívida desta cobrança já foi desfeita")
    amount = charge.split.debt_paid_cents
    acc.debt_reserved_cents -= amount
    acc.cash_debt_cents -= amount
    charge.debt_state = DebtState.APPLIED


def release_charge_debt(acc: RiderAccount, charge: PixCharge) -> None:
    """O Pix venceu ou a corrida cancelou antes de pagar: a dívida continua como estava."""
    if charge.debt_state is DebtState.RELEASED:
        return
    if charge.debt_state is not DebtState.RESERVED:
        raise ValueError("a cobrança já foi paga; use a devolução")
    acc.debt_reserved_cents -= charge.split.debt_paid_cents
    charge.debt_state = DebtState.RELEASED


def restore_charge_debt(acc: RiderAccount, charge: PixCharge) -> None:
    """Um Pix pago foi devolvido: a dívida abatida volta para a conta do motoqueiro."""
    if charge.debt_state is DebtState.RESTORED:
        return
    if charge.debt_state is not DebtState.APPLIED:
        raise ValueError("a dívida desta cobrança ainda não foi abatida")
    acc.cash_debt_cents += charge.split.debt_paid_cents
    charge.debt_state = DebtState.RESTORED


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
    debt_state: DebtState = DebtState.RESERVED


class PaymentProvider(Protocol):
    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split
    ) -> PixCharge: ...

    def refund(self, charge_id: str) -> None: ...
