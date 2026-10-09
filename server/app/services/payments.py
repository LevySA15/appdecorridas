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
from app.domain.fees import RiderAccount, add_cash_fee_debt, mark_entry_paid
from app.domain.payments import (
    DebtState,
    PaymentProvider,
    PixCharge,
    Split,
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
    block_for_unpaid,
    cancel,
    cancel_after_arrival_timeout,
    cancel_unpaid_pix,
    cash_pay_wait_expired,
    confirm_end_payment,
    confirm_qr_payment,
    on_pix_paid,
    pix_window_expired,
    release_from_queue,
    settle_passenger_debt,
)
from app.domain.types import PaymentMethod
from app.services.events import EventCollector


class PaymentService:
    def __init__(
        self,
        provider: PaymentProvider,
        fee_cfg: FeeConfig | None = None,
        ride_cfg: RideConfig | None = None,
        events: EventCollector | None = None,
    ) -> None:
        self.provider = provider
        self.fee_cfg = fee_cfg or FeeConfig()
        self.ride_cfg = ride_cfg or RideConfig()
        self.events = events

    def _emit(self, user_id: str | None, type: str, payload: dict | None = None) -> None:
        if self.events is not None and user_id is not None:
            self.events.add(user_id, type, payload)

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
        if known.purpose == "entry":
            return self._on_entry_paid(session, known)
        ride = repo.get_ride(session, known.ride_id, for_update=True)
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        ledger = PgLedger(session)
        ledger.post_charge_payment(charge.charge_id, charge.rider_id, charge.amount_cents, charge.split)
        is_current = repo.get_current_charge_id(session, ride.ride_id) == charge.charge_id
        if charge.purpose == "end":
            refund_needed = self._apply_end_payment(session, ride, acc, charge, is_current)
        else:
            refund_needed = on_pix_paid(ride) if is_current else True
            if not refund_needed:
                confirm_charge_debt(acc, charge)
        if refund_needed:
            self._refund(charge, acc, ledger)
            outcome = "refunded"
        else:
            outcome = "applied"
        repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        return outcome

    def _apply_end_payment(
        self, session: Session, ride: Ride, acc: RiderAccount, charge: PixCharge, is_current: bool
    ) -> bool:
        """Pix do QR do fim da corrida em dinheiro. Devolve True se o dinheiro deve voltar ao passageiro."""
        if not is_current or ride.state is not RideState.COMPLETED or ride.end_payment_confirmed:
            return True  # já foi pago em dinheiro (ou a cobrança é velha): o QR pago a mais volta
        was_blocked = ride.non_payment_reported
        if was_blocked:
            passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
            owed = min(passenger.unpaid_cents, ride.price_cents)
            if owed > 0:
                settle_passenger_debt(passenger, owed)
            repo.save_passenger_account(session, passenger)
        confirm_qr_payment(ride)
        confirm_charge_debt(acc, charge)
        self._emit(ride.rider_id, "payment_received", {"ride_id": ride.ride_id, "late": was_blocked})
        if was_blocked:
            self._emit(ride.passenger_id, "unblocked", {"ride_id": ride.ride_id})
        return False

    def _on_entry_paid(self, session: Session, known: PixCharge) -> str:
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        charge.debt_state = DebtState.APPLIED
        PgLedger(session).post_entry_fee(charge.rider_id, charge.amount_cents)
        mark_entry_paid(acc)
        repo.save_charge(session, charge)
        repo.save_rider_account(session, acc)
        self._emit(charge.rider_id, "entry_paid")
        return "applied"

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

    def _settle_cancellation(
        self,
        session: Session,
        ride: Ride,
        acc: RiderAccount | None,
        charge: PixCharge | None,
        result: CancelResult,
    ) -> None:
        """Grava um cancelamento: devolve o Pix pago (e a dívida) ou solta a dívida reservada."""
        if result.refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride.ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if result.refund_needed:
                self._refund(charge, acc, PgLedger(session))
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)

    def cancel_ride(self, session: Session, ride_id: str, now: float) -> CancelResult:
        """Cancelamento pelo passageiro: devolve o Pix se já estava pago e solta a dívida reservada."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel(ride, now, self.ride_cfg)
        self._settle_cancellation(session, ride, acc, charge, result)
        return result

    def cancel_after_arrival_timeout(self, session: Session, ride_id: str, now: float) -> CancelResult:
        """Passageiro não apareceu dentro do tempo de espera: cancela e devolve o Pix, se pago."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel_after_arrival_timeout(ride, now, self.ride_cfg)
        self._settle_cancellation(session, ride, acc, charge, result)
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

    # --- fim de corrida em dinheiro e taxa de entrada --------------------------------------

    def start_end_charge(self, session: Session, ride_id: str, fee_cents: int) -> PixCharge:
        """No fim de uma corrida em dinheiro: cria o QR do Pix com o valor (spec, seção 7.2)."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if (
            ride.payment_method is not PaymentMethod.CASH
            or ride.state is not RideState.COMPLETED
            or ride.rider_id is None
        ):
            raise InvalidTransition("só dá para gerar o QR de uma corrida em dinheiro já concluída")
        if ride.end_payment_confirmed:
            raise InvalidTransition("o pagamento desta corrida já foi confirmado")
        existing_id = repo.get_current_charge_id(session, ride_id)
        if existing_id is not None:
            return repo.get_charge(session, existing_id)
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        split = reserve_pix_split(acc, ride.price_cents, fee_cents, self.fee_cfg.max_debt_share)
        charge = self.provider.create_pix_charge(ride.ride_id, ride.rider_id, ride.price_cents, split, purpose="end")
        repo.add_charge(session, charge)
        repo.set_current_charge(session, ride_id, charge.charge_id)
        repo.save_rider_account(session, acc)
        return charge

    def confirm_cash_received(self, session: Session, ride_id: str, now: float) -> None:
        """O motoqueiro recebeu o dinheiro na mão: a taxa da corrida vira dívida dele."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
            raise InvalidTransition("só dá para confirmar o pagamento de uma corrida em dinheiro já concluída")
        if ride.end_payment_confirmed:
            raise InvalidTransition("o pagamento desta corrida já foi confirmado")
        if ride.non_payment_reported:
            raise InvalidTransition(
                "o passageiro está com o pagamento pendente: ele paga pelo Pix e o valor cai na sua conta"
            )
        confirm_end_payment(ride)
        acc, charge = self._rider_and_charge(session, ride)
        self._release_if_reserved(charge, acc)
        if acc is not None:
            add_cash_fee_debt(acc, ride.fee_cents or 0)
            repo.save_rider_account(session, acc)
        if charge is not None:
            repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        self._emit(ride.passenger_id, "payment_confirmed", {"ride_id": ride_id})

    def block_unpaid_cash_ride(self, session: Session, ride_id: str, now: float) -> bool:
        """Passou `cash_pay_wait_s` sem pagamento: bloqueia o passageiro. O motoqueiro não deve taxa."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if not cash_pay_wait_expired(ride, now, self.ride_cfg):
            return False
        if repo.get_current_charge_id(session, ride_id) is None:
            return False   # sem QR o passageiro não tem como pagar pelo Pix: não pode ser bloqueado
        qr_at = repo.ride_event_time(session, ride_id, "qr_created")
        if qr_at is not None and now - qr_at < self.ride_cfg.cash_pay_wait_s:
            return False   # QR criado depois (provedor voltou): o prazo recomeça nele
        passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
        block_for_unpaid(ride, passenger, now, self.ride_cfg)
        repo.save_ride(session, ride)
        repo.save_passenger_account(session, passenger)
        self._emit(ride.rider_id, "passenger_blocked", {"ride_id": ride_id})
        self._emit(
            ride.passenger_id, "payment_pending",
            {
                "ride_id": ride_id, "amount_cents": ride.price_cents,
                "charge_id": repo.get_current_charge_id(session, ride_id),
            },
        )
        return True

    def start_entry_charge(self, session: Session, rider_id: str) -> PixCharge:
        """Cobrança da entrada de R$ 50 (uma vez só, depois das corridas de teste)."""
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        if acc.entry_paid:
            raise InvalidTransition("a entrada já foi paga")
        open_charge = repo.find_open_entry_charge(session, rider_id)
        if open_charge is not None:
            return open_charge
        amount = self.fee_cfg.entry_fee_cents
        charge = self.provider.create_pix_charge("", rider_id, amount, Split(0, amount, 0), purpose="entry")
        repo.add_charge(session, charge)
        return charge
