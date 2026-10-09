"""Fluxo de dinheiro de uma corrida Pix (spec, seções 7 e 12).

Cada método trabalha dentro da transação de quem chama: nada de `commit` aqui. Se algo falhar no
meio (por exemplo, o provedor recusar um estorno), quem chamou desfaz a transação e o livro, a dívida
e a corrida voltam ao que eram; o aviso do provedor pode então ser tratado de novo.

Ordem de travas no banco: corrida, depois motoqueiro, depois cobrança.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.config import FeeConfig, RideConfig
from app.domain.fees import RiderAccount
from app.domain.payments import (
    DebtState,
    PaymentProvider,
    PixCharge,
    confirm_charge_debt,
    release_charge_debt,
    reserve_pix_split,
    restore_charge_debt,
)
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    cancel,
    cancel_unpaid_pix,
    on_pix_paid,
    pix_window_expired,
    release_from_queue,
)
from app.domain.types import PaymentMethod


class PaymentService:
    def __init__(
        self,
        provider: PaymentProvider,
        fee_cfg: FeeConfig | None = None,
        ride_cfg: RideConfig | None = None,
    ) -> None:
        self.provider = provider
        self.fee_cfg = fee_cfg or FeeConfig()
        self.ride_cfg = ride_cfg or RideConfig()

    # --- auxiliares ---------------------------------------------------------------

    def _rider_and_charge(
        self, session: Session, ride: Ride
    ) -> tuple[RiderAccount | None, PixCharge | None]:
        if ride.rider_id is None:
            return None, None
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        charge_id = repo.get_current_charge_id(session, ride.ride_id)
        charge = repo.get_charge(session, charge_id, for_update=True) if charge_id else None
        return acc, charge

    def _refund(self, charge: PixCharge, acc: RiderAccount, ledger: PgLedger) -> None:
        """Devolve um Pix pago: provedor, livro-caixa e dívida (a reservada é solta, a abatida volta)."""
        self.provider.refund(charge.charge_id)
        ledger.post_refund(charge.charge_id)
        charge.refunded = True
        if charge.debt_state is DebtState.APPLIED:
            restore_charge_debt(acc, charge)
        elif charge.debt_state is DebtState.RESERVED:
            release_charge_debt(acc, charge)

    def _release_if_reserved(self, charge: PixCharge | None, acc: RiderAccount | None) -> None:
        if charge is not None and acc is not None and charge.debt_state is DebtState.RESERVED:
            release_charge_debt(acc, charge)

    # --- casos de uso --------------------------------------------------------------

    def start_pix_charge(self, session: Session, ride_id: str, fee_cents: int) -> PixCharge:
        """Chamado quando o motoqueiro aceita uma corrida Pix: reserva a dívida e cria a cobrança."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.payment_method is not PaymentMethod.PIX:
            raise InvalidTransition("esta corrida não é paga por Pix")
        if ride.rider_id is None or ride.state not in (RideState.QUEUED, RideState.ACCEPTED):
            raise InvalidTransition("só dá para cobrar uma corrida aceita por um motoqueiro")
        existing_id = repo.get_current_charge_id(session, ride_id)
        if existing_id is not None:
            return repo.get_charge(session, existing_id)
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        split = reserve_pix_split(acc, ride.price_cents, fee_cents, self.fee_cfg.max_debt_share)
        charge = self.provider.create_pix_charge(ride.ride_id, ride.rider_id, ride.price_cents, split)
        repo.add_charge(session, charge)
        repo.set_current_charge(session, ride_id, charge.charge_id)
        repo.save_rider_account(session, acc)
        return charge

    def on_provider_event(self, session: Session, event: dict) -> str:
        """Trata o aviso de "pago" do provedor. Devolve "applied", "refunded" ou "duplicate"."""
        if event.get("type") != "paid":
            raise ValueError(f"tipo de aviso desconhecido: {event.get('type')}")
        if not repo.first_time_event(session, event["event_id"]):
            return "duplicate"
        known = repo.get_charge(session, event["charge_id"])
        ride = repo.get_ride(session, known.ride_id, for_update=True)
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        ledger = PgLedger(session)
        ledger.post_charge_payment(charge.charge_id, charge.rider_id, charge.amount_cents, charge.split)
        is_current = repo.get_current_charge_id(session, ride.ride_id) == charge.charge_id
        refund_needed = on_pix_paid(ride) if is_current else True
        if refund_needed:
            self._refund(charge, acc, ledger)
            outcome = "refunded"
        else:
            confirm_charge_debt(acc, charge)
            outcome = "applied"
        repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        return outcome

    def expire_unpaid_pix(self, session: Session, ride_id: str, now: float) -> bool:
        """Cancela a corrida se o passageiro não pagou o Pix dentro da janela. Devolve se cancelou."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if not pix_window_expired(ride, now, self.ride_cfg):
            return False
        acc, charge = self._rider_and_charge(session, ride)
        cancel_unpaid_pix(ride)
        self._release_if_reserved(charge, acc)
        if charge is not None:
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        return True

    def cancel_ride(self, session: Session, ride_id: str, now: float) -> CancelResult:
        """Cancelamento pelo passageiro: devolve o Pix se já estava pago e solta a dívida reservada."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel(ride, now, self.ride_cfg)
        if result.refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if result.refund_needed:
                self._refund(charge, acc, PgLedger(session))
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        return result

    def release_queued_ride(self, session: Session, ride_id: str, now: float) -> bool:
        """Tira a corrida da fila e volta para a busca. Devolve se houve estorno de Pix pago."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        refund_needed = release_from_queue(ride, now)
        if refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if refund_needed:
                self._refund(charge, acc, PgLedger(session))
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        repo.set_current_charge(session, ride_id, None)
        return refund_needed
