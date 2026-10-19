"""O que o passageiro faz com o dinheiro dele no app: pagar a taxa pendente, recarregar o saldo e recorrer.

Cada método trabalha dentro da transação de quem chama (nada de `commit` aqui). Ordem de travas: o
passageiro primeiro, depois a linha da taxa.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.pg_ledger import PgLedger
from app.domain.balance import Withdrawal, apply_pending_payment, credit, spend_up_to, waive_pending
from app.domain.ids import new_id
from app.domain.money import brl
from app.domain.payments import PixCharge, Split
from app.domain.pix_key import normalize_pix_key
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import NotAllowed
from app.services.trips import NotYourRide


class NothingToPay(Exception):
    """O passageiro não tem taxa pendente para pagar."""


class TopupDisabled(NotAllowed):
    """A recarga de saldo está desligada (depende da resposta do advogado, spec seção 7.5)."""


class WithdrawDisabled(NotAllowed):
    """O saque do saldo está desligado (depende da resposta do advogado, spec seção 7.5)."""


class AppealNotAllowed(Exception):
    """O recurso não pode ser pedido ou decidido agora (já pedido, fora do prazo, já decidido, não pedido)."""


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

    # --- saque do saldo -------------------------------------------------------------------------

    def withdraw(self, session: Session, passenger_id: str, amount_cents: int, pix_key: str, now: float) -> Withdrawal:
        """Saca parte do saldo por Pix. Desligado por padrão (ver `BalanceConfig`).

        Primeiro tudo o que pode recusar, depois o débito e o livro, e o Pix por último: se o provedor falhar, a
        unidade de trabalho inteira é desfeita por quem chama e nada fica gravado.
        """
        limits = self.cfg.balance
        if not limits.withdraw_enabled:
            raise WithdrawDisabled("O saque do saldo ainda não está disponível.")
        if not limits.withdraw_min_cents <= amount_cents <= limits.withdraw_max_cents:
            raise ValueError(f"O saque vai de {brl(limits.withdraw_min_cents)} a {brl(limits.withdraw_max_cents)}.")
        key = normalize_pix_key(pix_key)
        passenger = repo.get_passenger_account(session, passenger_id, for_update=True)
        if passenger.unpaid_cents > 0 or repo.pending_cancel_fee(session, passenger_id, for_update=True) is not None:
            raise NotAllowed("Pague o que está pendente antes de sacar.")
        if passenger.balance_cents < amount_cents:
            raise NotAllowed("Seu saldo é menor que o valor do saque.")
        withdrawal_id = new_id("wd")
        spend_up_to(passenger, amount_cents)
        PgLedger(session).post_withdrawal(withdrawal_id, passenger_id, amount_cents)
        repo.save_passenger_account(session, passenger)
        provider_ref = self.payments.provider.payout(withdrawal_id, key.value, amount_cents)
        withdrawal = Withdrawal(withdrawal_id, passenger_id, amount_cents, key.kind, key.masked, provider_ref, now)
        repo.add_withdrawal(session, withdrawal)
        self.events.add(passenger_id, "balance_changed", {"balance_cents": passenger.balance_cents})
        self.events.add(
            passenger_id, "withdrawal_done",
            {"withdrawal_id": withdrawal_id, "amount_cents": amount_cents, "balance_cents": passenger.balance_cents},
        )
        return withdrawal

    # --- recurso da taxa -----------------------------------------------------------------------

    def file_appeal(self, session: Session, passenger_id: str, ride_id: str, text: str, now: float) -> None:
        """O passageiro pede revisão da taxa (uma vez, até `appeal_window_s` depois do cancelamento)."""
        if repo.get_cancel_fee(session, ride_id).passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        text = text.strip()
        if not 3 <= len(text) <= 500:
            raise ValueError("Conte em poucas palavras o que aconteceu (de 3 a 500 letras).")
        repo.get_passenger_account(session, passenger_id, for_update=True)
        fee = repo.get_cancel_fee(session, ride_id, for_update=True)
        if fee.appeal_state != "none":
            raise AppealNotAllowed("Você já pediu a revisão desta taxa.")
        if now - fee.created_at > self.cfg.rides.appeal_window_s:
            raise AppealNotAllowed("O prazo para pedir revisão acabou.")
        fee.appeal_state, fee.appeal_text, fee.appealed_at = "open", text, now
        repo.save_cancel_fee(session, fee)
        repo.log_ride_event(session, ride_id, "fee_appeal_opened", {}, now)
        for admin_id in queries.admin_ids(session):
            self.events.add(admin_id, "appeal_opened", {"ride_id": ride_id})

    def decide_appeal(
        self, session: Session, admin_id: str, ride_id: str, accept: bool, note: str, now: float
    ) -> None:
        """O administrador decide. Aceitar perdoa a pendência e devolve ao saldo do passageiro tudo o que já foi
        cobrado (a empresa paga; o motoqueiro fica com a taxa). Recusar não muda nada de dinheiro."""
        passenger_id = repo.get_cancel_fee(session, ride_id).passenger_id
        passenger = repo.get_passenger_account(session, passenger_id, for_update=True)
        fee = repo.get_cancel_fee(session, ride_id, for_update=True)
        if fee.appeal_state == "none":
            raise AppealNotAllowed("Este recurso não foi pedido.")
        if fee.appeal_state != "open":
            raise AppealNotAllowed("Este recurso já foi decidido.")
        waived = credited = 0
        if accept:
            waived = waive_pending(fee)
            passenger.unpaid_cents = max(0, passenger.unpaid_cents - waived)
            credited = fee.from_balance_cents + fee.retained_cents + fee.paid_later_cents - fee.credited_back_cents
            if credited > 0:
                PgLedger(session).post_credit_from_company(f"fee:{ride_id}:appeal", passenger_id, credited)
                credit(passenger, credited)
                fee.credited_back_cents += credited
        fee.appeal_state = "accepted" if accept else "rejected"
        fee.decided_at, fee.decided_by, fee.decision_note = now, admin_id, note.strip() or None
        repo.save_passenger_account(session, passenger)
        repo.save_cancel_fee(session, fee)
        repo.log_ride_event(session, ride_id, "fee_appeal_decided", {"decision": fee.appeal_state, "by": admin_id}, now)
        self.events.add(
            passenger_id, "appeal_decided",
            {"ride_id": ride_id, "decision": "accept" if accept else "reject", "credited_cents": credited},
        )
        if waived and passenger.unpaid_cents == 0:
            self.events.add(passenger_id, "unblocked", {"ride_id": ride_id})
