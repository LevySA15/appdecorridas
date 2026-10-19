"""O que o passageiro faz com o dinheiro dele no app: pagar a taxa pendente, recarregar o saldo e recorrer.

Cada método trabalha dentro da transação de quem chama (nada de `commit` aqui). Ordem de travas: o
passageiro primeiro, depois a linha da taxa.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.pg_ledger import PgLedger
from app.domain.balance import apply_pending_payment, spend_up_to
from app.domain.money import brl
from app.domain.payments import PixCharge, Split
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import NotAllowed


class NothingToPay(Exception):
    """O passageiro não tem taxa pendente para pagar."""


class TopupDisabled(NotAllowed):
    """A recarga de saldo está desligada (depende da resposta do advogado, spec seção 7.5)."""


class PassengerMoneyService:
    def __init__(self, payments: PaymentService, events: EventCollector, cfg: AppConfig | None = None) -> None:
        self.payments = payments
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    # --- pagar a taxa pendente ----------------------------------------------------------------

    def pay_pending(self, session: Session, passenger_id: str, now: float) -> PixCharge | None:
        """Paga a taxa de cancelamento pendente. Devolve `None` se o saldo cobriu tudo; senão a cobrança Pix do
        valor inteiro (o saldo não se mistura com o Pix numa cobrança só)."""
        passenger = repo.get_passenger_account(session, passenger_id, for_update=True)
        fee = repo.pending_cancel_fee(session, passenger_id, for_update=True)
        if fee is None:
            raise NothingToPay("Você não tem nada para pagar.")
        if passenger.balance_cents >= fee.pending_cents:
            amount = fee.pending_cents
            spend_up_to(passenger, amount)
            PgLedger(session).post_spend_balance(f"fee:{fee.ride_id}:pay", passenger_id, fee.rider_id, amount)
            apply_pending_payment(fee, amount)
            passenger.unpaid_cents = max(0, passenger.unpaid_cents - amount)
            repo.save_passenger_account(session, passenger)
            repo.save_cancel_fee(session, fee)
            self.events.add(
                passenger_id, "fee_paid",
                {"ride_id": fee.ride_id, "amount_cents": amount, "balance_cents": passenger.balance_cents},
            )
            if passenger.unpaid_cents == 0:
                self.events.add(passenger_id, "unblocked", {"ride_id": fee.ride_id})
            self.events.add(
                fee.rider_id, "payment_received", {"ride_id": fee.ride_id, "amount_cents": amount, "kind": "cancel_fee"}
            )
            return None
        open_charge = repo.find_open_charge(session, fee.ride_id, "fee")
        if open_charge is not None and open_charge.amount_cents == fee.pending_cents:
            return open_charge
        charge = self.payments.provider.create_pix_charge(
            fee.ride_id, fee.rider_id, fee.pending_cents, Split(fee.pending_cents, 0, 0), purpose="fee"
        )
        repo.add_charge(session, charge)
        return charge

    # --- recarga do saldo ------------------------------------------------------------------------

    def topup(self, session: Session, passenger_id: str, amount_cents: int, now: float) -> PixCharge:
        """Cobrança Pix para recarregar o saldo. Desligada por padrão (ver `BalanceConfig`)."""
        limits = self.cfg.balance
        if not limits.topup_enabled:
            raise TopupDisabled("A recarga de saldo ainda não está disponível.")
        if not limits.topup_min_cents <= amount_cents <= limits.topup_max_cents:
            raise ValueError(f"A recarga vai de {brl(limits.topup_min_cents)} a {brl(limits.topup_max_cents)}.")
        open_charge = repo.find_open_topup_charge(session, passenger_id)
        if open_charge is not None and open_charge.amount_cents == amount_cents:
            return open_charge
        charge = self.payments.provider.create_pix_charge(
            "", "", amount_cents, Split(0, amount_cents, 0), purpose="topup", passenger_id=passenger_id
        )
        repo.add_charge(session, charge)
        return charge
