"""Fluxo de dinheiro de uma corrida Pix (spec, seções 7 e 12).

Cada método trabalha dentro da transação de quem chama: nada de `commit` aqui. Se algo falhar no
meio (por exemplo, o provedor recusar um estorno), quem chamou desfaz a transação e o livro, a dívida
e a corrida voltam ao que eram; o aviso do provedor pode então ser tratado de novo.

Ordem de travas no banco: corrida, depois motoqueiro, depois cobrança.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.balance import (
    CancelFee,
    FeePlan,
    apply_pending_payment,
    credit,
    plan_fee_collection,
    spend_up_to,
)
from app.domain.config import FeeConfig, RideConfig
from app.domain.fees import RiderAccount, add_cash_fee_debt, mark_entry_paid, offer_block_reason
from app.domain.payments import (
    DebtState,
    PaymentProvider,
    PixCharge,
    RefundUndeliverable,
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
from app.infra.redis_store import PositionStore
from app.services.events import EventCollector


@dataclass(frozen=True)
class CancelOutcome:
    """O que aconteceu num cancelamento: a taxa (se tardio), de onde ela saiu e para onde foi a devolução."""

    fee_cents: int
    refund_needed: bool
    refund_to: str | None = None        # "pix" | "balance" | None
    from_balance_cents: int = 0
    retained_cents: int = 0
    pending_cents: int = 0


class PaymentService:
    def __init__(
        self,
        provider: PaymentProvider,
        fee_cfg: FeeConfig | None = None,
        ride_cfg: RideConfig | None = None,
        events: EventCollector | None = None,
        positions: PositionStore | None = None,
    ) -> None:
        self.positions = positions
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

    def _refund(
        self, session: Session, passenger_id: str, charge: PixCharge, acc: RiderAccount, ledger: PgLedger,
        *, keep_cents: int = 0,
    ) -> str:
        """Devolve um Pix pago: provedor, livro-caixa e dívida (a reservada é solta, a abatida volta).

        `keep_cents` fica com o motoqueiro (taxa de cancelamento retida) e só o resto volta. Se a devolução
        não chega à chave Pix do passageiro, o resto vira saldo dele no app. Devolve `"pix"` ou `"balance"`.
        """
        send = charge.amount_cents - keep_cents
        destination = "pix"
        try:
            if send > 0:
                self.provider.refund(charge.charge_id, send)
            ledger.post_refund(charge.charge_id, keep_cents=keep_cents)
        except RefundUndeliverable:
            ledger.post_refund_to_balance(charge.charge_id, passenger_id, keep_cents=keep_cents)
            passenger = repo.get_passenger_account(session, passenger_id, for_update=True)
            credit(passenger, send)
            repo.save_passenger_account(session, passenger)
            destination = "balance"
        charge.refunded = True
        if charge.debt_state is DebtState.APPLIED:
            restore_charge_debt(acc, charge)
        elif charge.debt_state is DebtState.RESERVED:
            release_charge_debt(acc, charge)
        return destination

    def _block_for_debt(self, session: Session, acc: RiderAccount) -> None:
        """A dívida da taxa chegou ao limite: sem corrida em andamento, o motoqueiro vai para "não estou" e sai do
        mapa na hora; com corrida em andamento ela segue e, ao acabar, ele fica em "não estou". Em qualquer caso é avisado."""
        if queries.rider_active_ride_id(session, acc.rider_id) is None:
            profile = session.get(RiderProfileRow, acc.rider_id)
            profile.online = False
            session.flush()
            if self.positions is not None:
                self.positions.remove(acc.rider_id)
        self._emit(
            acc.rider_id, "debt_required",
            {"cash_debt_cents": acc.cash_debt_cents, "debt_limit_cents": self.fee_cfg.cash_debt_limit_cents},
        )

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
        if known.purpose == "topup":
            return self._on_topup_paid(session, known)
        if known.purpose == "fee":
            return self._on_fee_paid(session, known)
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
                self._emit(ride.passenger_id, "pix_confirmed", {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents})
                self._emit(ride.rider_id, "payment_received", {"ride_id": ride.ride_id, "late": False})
        if refund_needed:
            keep = self._retain_for_pending_fee(session, ride, charge)
            destination = self._refund(session, ride.passenger_id, charge, acc, ledger, keep_cents=keep)
            if keep:
                self._announce_fee_paid(session, ride, keep)
            if charge.amount_cents - keep > 0:
                refunded = {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents - keep, "to": destination}
                if destination == "balance":
                    refunded["balance_cents"] = repo.get_passenger_account(session, ride.passenger_id).balance_cents
                self._emit(ride.passenger_id, "payment_refunded", refunded)
            outcome = "refunded"
        else:
            outcome = "applied"
        repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        return outcome

    def _retain_for_pending_fee(self, session: Session, ride: Ride, charge: PixCharge) -> int:
        """Pix que chega depois de a corrida ser cancelada com taxa pendente: o Pix cobre a taxa e só o resto volta.

        Sem isto, quem pagou o Pix e cancelou quase junto recebia tudo de volta e continuava devendo a taxa.
        Devolve quanto fica retido para o motoqueiro (0 se não há taxa pendente).
        """
        if ride.state is not RideState.CANCELLED or charge.purpose != "ride":
            return 0
        passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
        try:
            fee = repo.get_cancel_fee(session, ride.ride_id, for_update=True)
        except LookupError:
            return 0
        if fee.pending_cents <= 0:
            return 0
        keep = min(fee.pending_cents, charge.amount_cents)
        apply_pending_payment(fee, keep)
        passenger.unpaid_cents = max(0, passenger.unpaid_cents - keep)
        repo.save_passenger_account(session, passenger)
        repo.save_cancel_fee(session, fee)
        return keep

    def _announce_fee_paid(self, session: Session, ride: Ride, amount_cents: int) -> None:
        """Avisa que a taxa pendente foi paga (e que o passageiro foi liberado, se era só isso que ele devia)."""
        passenger = repo.get_passenger_account(session, ride.passenger_id)
        self._emit(
            ride.passenger_id, "fee_paid",
            {"ride_id": ride.ride_id, "amount_cents": amount_cents, "balance_cents": passenger.balance_cents},
        )
        if passenger.unpaid_cents == 0:
            self._emit(ride.passenger_id, "unblocked", {"ride_id": ride.ride_id})
        self._emit(
            ride.rider_id, "payment_received",
            {"ride_id": ride.ride_id, "amount_cents": amount_cents, "kind": "cancel_fee"},
        )

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

    def _on_topup_paid(self, session: Session, known: PixCharge) -> str:
        """Recarga do saldo do passageiro paga."""
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        passenger = repo.get_passenger_account(session, charge.passenger_id, for_update=True)
        charge.paid = True
        charge.debt_state = DebtState.APPLIED
        PgLedger(session).post_topup(charge.charge_id, charge.passenger_id, charge.amount_cents)
        credit(passenger, charge.amount_cents)
        repo.save_passenger_account(session, passenger)
        repo.save_charge(session, charge)
        self._emit(charge.passenger_id, "balance_changed", {"balance_cents": passenger.balance_cents})
        return "applied"

    def _on_fee_paid(self, session: Session, known: PixCharge) -> str:
        """Pix da taxa de cancelamento pendente. Se a taxa já foi paga ou perdoada no meio tempo (recurso aceito),
        o dinheiro volta para o passageiro."""
        ride = repo.get_ride(session, known.ride_id)
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
        fee = repo.get_cancel_fee(session, known.ride_id, for_update=True)
        charge.paid = True
        ledger = PgLedger(session)
        ledger.post_charge_payment(charge.charge_id, charge.rider_id, charge.amount_cents, charge.split)
        if fee.pending_cents == charge.amount_cents:
            apply_pending_payment(fee, charge.amount_cents)
            passenger.unpaid_cents = max(0, passenger.unpaid_cents - charge.amount_cents)
            charge.debt_state = DebtState.APPLIED
            repo.save_passenger_account(session, passenger)
            repo.save_cancel_fee(session, fee)
            self._emit(
                ride.passenger_id, "fee_paid",
                {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents, "balance_cents": passenger.balance_cents},
            )
            if passenger.unpaid_cents == 0:
                self._emit(ride.passenger_id, "unblocked", {"ride_id": ride.ride_id})
            self._emit(
                charge.rider_id, "payment_received",
                {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents, "kind": "cancel_fee"},
            )
            outcome = "applied"
        else:
            destination = self._refund(session, ride.passenger_id, charge, acc, ledger)
            refunded = {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents, "to": destination}
            if destination == "balance":
                refunded["balance_cents"] = repo.get_passenger_account(session, ride.passenger_id).balance_cents
            self._emit(ride.passenger_id, "payment_refunded", refunded)
            outcome = "refunded"
        repo.save_charge(session, charge)
        repo.save_rider_account(session, acc)
        return outcome

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
        now: float,
        reason: str,
        progress: float | None,
    ) -> CancelOutcome:
        """Grava um cancelamento: cobra a taxa (saldo, retenção do Pix, pendência), devolve o Pix pago
        (e a dívida) ou solta a dívida reservada."""
        if result.refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride.ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        plan = FeePlan(0, 0, 0)
        if result.fee_cents > 0 and ride.rider_id is not None:
            plan = self._charge_fee(session, ride, result, charge, now, reason, progress)
        refund_to = None
        if charge is not None and acc is not None:
            if result.refund_needed:
                refund_to = self._refund(
                    session, ride.passenger_id, charge, acc, PgLedger(session), keep_cents=plan.retained
                )
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        if result.fee_cents > 0 and ride.rider_id is not None:
            self._emit(
                ride.passenger_id, "cancel_fee",
                {
                    "ride_id": ride.ride_id, "fee_cents": result.fee_cents, "from_balance_cents": plan.from_balance,
                    "retained_cents": plan.retained, "pending_cents": plan.pending,
                    "balance_cents": repo.get_passenger_account(session, ride.passenger_id).balance_cents,
                },
            )
        return CancelOutcome(
            result.fee_cents, result.refund_needed, refund_to, plan.from_balance, plan.retained, plan.pending
        )

    def _charge_fee(
        self, session: Session, ride: Ride, result: CancelResult, charge: PixCharge | None, now: float,
        reason: str, progress: float | None,
    ) -> FeePlan:
        """Cobra a taxa do cancelamento tardio: primeiro o saldo, depois o que o Pix pago puder cobrir (a
        devolução é feita por quem chama, com `keep_cents`); o resto vira pendência e bloqueia novos pedidos."""
        passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
        held = charge.amount_cents if result.refund_needed and charge is not None else 0
        plan = plan_fee_collection(result.fee_cents, passenger.balance_cents, held)
        if plan.from_balance:
            spend_up_to(passenger, plan.from_balance)
            PgLedger(session).post_spend_balance(
                f"fee:{ride.ride_id}:cancel", ride.passenger_id, ride.rider_id, plan.from_balance
            )
        passenger.unpaid_cents += plan.pending
        repo.save_passenger_account(session, passenger)
        repo.add_cancel_fee(
            session,
            CancelFee(
                ride_id=ride.ride_id, passenger_id=ride.passenger_id, rider_id=ride.rider_id,
                fee_cents=result.fee_cents, reason=reason, created_at=now, progress=progress,
                from_balance_cents=plan.from_balance, retained_cents=plan.retained, pending_cents=plan.pending,
            ),
        )
        return plan

    def cancel_ride(
        self, session: Session, ride_id: str, now: float, progress: float | None = None
    ) -> CancelOutcome:
        """Cancelamento pelo passageiro: cobra a taxa se foi tardio, devolve o Pix se já estava pago e solta a
        dívida reservada. `progress` é quanto a moto já andou até o ponto de embarque."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel(ride, now, self.ride_cfg, progress)
        return self._settle_cancellation(session, ride, acc, charge, result, now, "passenger", progress)

    def cancel_after_arrival_timeout(self, session: Session, ride_id: str, now: float) -> CancelOutcome:
        """Passageiro não apareceu dentro do tempo de espera: cancela, cobra a taxa máxima e devolve o Pix, se pago."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel_after_arrival_timeout(ride, now, self.ride_cfg)
        return self._settle_cancellation(session, ride, acc, charge, result, now, "arrival_timeout", 1.0)

    def release_queued_ride(self, session: Session, ride_id: str, now: float) -> bool:
        """Tira a corrida da fila e volta para a busca. Devolve se houve estorno de Pix pago."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        refund_needed = release_from_queue(ride, now)
        if refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if refund_needed:
                self._refund(session, ride.passenger_id, charge, acc, PgLedger(session))
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
        """O motoqueiro recebeu o dinheiro na mão: a taxa da corrida vira dívida dele.

        Vale também depois do bloqueio automático, como correção (o passageiro pagou em dinheiro e o
        motoqueiro esqueceu de confirmar): o passageiro é desbloqueado. Um QR pago depois é devolvido.
        """
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
            raise InvalidTransition("só dá para confirmar o pagamento de uma corrida em dinheiro já concluída")
        if ride.end_payment_confirmed:
            raise InvalidTransition("o pagamento desta corrida já foi confirmado")
        was_blocked = ride.non_payment_reported
        if was_blocked:
            confirm_qr_payment(ride)
        else:
            confirm_end_payment(ride)
        acc, charge = self._rider_and_charge(session, ride)
        self._release_if_reserved(charge, acc)
        if acc is not None:
            had_block = offer_block_reason(acc, self.fee_cfg) is not None
            add_cash_fee_debt(acc, ride.fee_cents or 0)
            if not had_block and offer_block_reason(acc, self.fee_cfg) == "divida_pendente":
                self._block_for_debt(session, acc)
            repo.save_rider_account(session, acc)
        if charge is not None:
            repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        if was_blocked:
            passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
            owed = min(passenger.unpaid_cents, ride.price_cents)
            if owed > 0:
                settle_passenger_debt(passenger, owed)
            repo.save_passenger_account(session, passenger)
            self._emit(ride.passenger_id, "unblocked", {"ride_id": ride_id})
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
