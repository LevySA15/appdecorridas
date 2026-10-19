"""Saldo do passageiro e taxa de cancelamento tardio (regras puras, sem banco).

O saldo é dinheiro do passageiro guardado no app (crédito de devolução que não chegou, recarga).
Hoje ele só paga a taxa de cancelamento. A taxa é cobrada nesta ordem: saldo, retenção da devolução
do Pix já pago, pendência (que bloqueia novos pedidos até ser paga).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.rides import PassengerAccount


def credit(acc: PassengerAccount, cents: int) -> None:
    if cents <= 0:
        raise ValueError("o crédito no saldo precisa ser positivo")
    acc.balance_cents += cents


def spend_up_to(acc: PassengerAccount, cents: int) -> int:
    """Tira do saldo até `cents`, nunca mais do que há. Devolve quanto saiu."""
    if cents < 0:
        raise ValueError("o gasto do saldo não pode ser negativo")
    spent = min(acc.balance_cents, cents)
    acc.balance_cents -= spent
    return spent


@dataclass(frozen=True)
class FeePlan:
    from_balance: int
    retained: int
    pending: int


def plan_fee_collection(fee_cents: int, balance_cents: int, held_cents: int) -> FeePlan:
    """Como cobrar `fee_cents`: do saldo primeiro, depois do Pix pago (`held_cents`), o resto fica pendente."""
    if fee_cents < 0 or balance_cents < 0 or held_cents < 0:
        raise ValueError("valores negativos não valem")
    from_balance = min(balance_cents, fee_cents)
    rest = fee_cents - from_balance
    retained = min(rest, held_cents)
    return FeePlan(from_balance, retained, rest - retained)


@dataclass
class CancelFee:
    """Tudo o que aconteceu com a taxa de cancelamento de uma corrida.

    Sempre vale: from_balance + retained + pending + paid_later + waived == fee_cents.
    """

    ride_id: str
    passenger_id: str
    rider_id: str
    fee_cents: int
    reason: str                 # "passenger" (cancelou) ou "arrival_timeout" (não apareceu)
    created_at: float
    progress: float | None = None
    from_balance_cents: int = 0
    retained_cents: int = 0
    pending_cents: int = 0
    paid_later_cents: int = 0
    waived_cents: int = 0
    credited_back_cents: int = 0
    appeal_state: str = "none"  # none | open | accepted | rejected
    appeal_text: str | None = None
    appealed_at: float | None = None
    decided_at: float | None = None
    decided_by: str | None = None
    decision_note: str | None = None


def apply_pending_payment(fee: CancelFee, cents: int) -> None:
    """A pendência (toda ou uma parte) foi paga depois do cancelamento."""
    if cents <= 0 or cents > fee.pending_cents:
        raise ValueError("valor inválido para pagar a taxa pendente")
    fee.pending_cents -= cents
    fee.paid_later_cents += cents


def waive_pending(fee: CancelFee) -> int:
    """Perdoa o que ainda estava pendente (recurso aceito). Devolve o valor perdoado."""
    waived = fee.pending_cents
    fee.pending_cents = 0
    fee.waived_cents += waived
    return waived
