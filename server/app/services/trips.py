"""Andamento da corrida: chegada, capacete, código, fim, cancelamento, fila e avaliação (spec, seção 5)."""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RatingRow, RiderProfileRow
from app.domain.fees import count_completed_ride, offer_block_reason
from app.domain.payments import PaymentProviderError
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    complete,
    confirm_helmet,
    mark_arrived,
    promote_from_queue,
    start_ride,
)
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.payments import PaymentService


class NotYourRide(Exception):
    """A corrida é de outra pessoa."""


class AlreadyRated(Exception):
    """Esta pessoa já avaliou esta corrida."""


class Dispatcher(Protocol):
    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None: ...

    def withdraw_offer(self, session: Session, ride_id: str) -> None: ...


class TripService:
    def __init__(
        self, payments: PaymentService, dispatcher: Dispatcher, events: EventCollector, cfg: AppConfig | None = None
    ) -> None:
        self.payments = payments
        self.dispatcher = dispatcher
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def _rider_ride(self, session: Session, rider_id: str, ride_id: str) -> Ride:
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.rider_id != rider_id:
            raise NotYourRide("Essa corrida não é sua.")
        return ride

    # --- etapas feitas pelo motoqueiro -------------------------------------------------------

    def arrive(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        mark_arrived(ride, now)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "arrived", {}, now)
        self.events.add(ride.passenger_id, "rider_arrived", {"ride_id": ride_id})

    def confirm_helmet(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        confirm_helmet(ride)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "helmet_confirmed", {}, now)

    def start_trip(self, session: Session, rider_id: str, ride_id: str, pin: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        start_ride(ride, pin)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "started", {}, now)
        self.events.add(ride.passenger_id, "trip_started", {"ride_id": ride_id})

    def complete_trip(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        self.lock_queued_ride(session, rider_id)
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        complete(ride, now)
        count_completed_ride(acc)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        if offer_block_reason(acc, self.cfg.fees) is not None:
            # chegou nas corridas de teste sem pagar a entrada: para de aparecer como disponível e o app avisa
            session.get(RiderProfileRow, rider_id).online = False
            self.events.add(rider_id, "entry_required", {"entry_fee_cents": self.cfg.fees.entry_fee_cents})
        repo.log_ride_event(session, ride_id, "completed", {}, now)
        pay = None
        if ride.payment_method is PaymentMethod.CASH:
            try:
                with session.begin_nested():
                    charge = self.payments.start_end_charge(session, ride_id, ride.fee_cents or 0)
                pay = {"charge_id": charge.charge_id, "amount_cents": charge.amount_cents}
                repo.log_ride_event(session, ride_id, "qr_created", {}, now)
            except PaymentProviderError as exc:
                # Pix fora do ar: a corrida termina do mesmo jeito e o dinheiro vivo continua valendo.
                # A varredura cria o QR quando o provedor voltar.
                repo.log_ride_event(session, ride_id, "qr_failed", {"error": str(exc)[:200]}, now)
        payload = {
            "ride_id": ride_id, "price_cents": ride.price_cents, "method": ride.payment_method.value, "pay": pay,
        }
        self.events.add(ride.passenger_id, "trip_completed", payload)
        self.events.add(rider_id, "trip_completed", payload)
        self.after_ride_ends(session, rider_id, now)

    def confirm_cash_received(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        self._rider_ride(session, rider_id, ride_id)
        self.payments.confirm_cash_received(session, ride_id, now)
        repo.log_ride_event(session, ride_id, "cash_confirmed", {}, now)

    # --- fila -----------------------------------------------------------------------------------

    def lock_queued_ride(self, session: Session, rider_id: str) -> None:
        """Trava já a corrida da fila do motoqueiro, se houver.

        A ordem das travas é sempre: corrida, corrida da fila, motoqueiro. Quem termina ou cancela a
        corrida atual chama isto antes de travar o motoqueiro; senão o Pix ou o cancelamento da corrida
        da fila (que travam a fila e depois o motoqueiro) podem travar um ao outro (impasse).
        """
        queued_id = queries.queued_ride_id_of_rider(session, rider_id)
        if queued_id is not None:
            repo.get_ride(session, queued_id, for_update=True)

    def after_ride_ends(self, session: Session, rider_id: str, now: float) -> None:
        """O motoqueiro ficou livre: assume a corrida da fila, ou a devolve se ele não pode continuar."""
        if queries.rider_active_ride_id(session, rider_id) is not None:
            return
        queued_id = queries.queued_ride_id_of_rider(session, rider_id)
        if queued_id is None:
            return
        queued = repo.get_ride(session, queued_id, for_update=True)
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        if offer_block_reason(acc, self.cfg.fees) is not None:
            refunded = self.payments.release_queued_ride(session, queued_id, now)
            repo.log_ride_event(
                session, queued_id, "queue_released", {"reason": "entrada pendente", "refunded": refunded}, now
            )
            self.events.add(queued.passenger_id, "queue_released", {"ride_id": queued_id, "refunded": refunded})
            self.dispatcher.offer_next(session, queued_id, now)
            return
        promote_from_queue(queued, now)
        repo.save_ride(session, queued)
        repo.log_ride_event(session, queued_id, "promoted", {}, now)
        self.events.add(queued.passenger_id, "rider_on_the_way", {"ride_id": queued_id})
        self.events.add(rider_id, "next_ride", {"ride_id": queued_id})

    # --- cancelamento ---------------------------------------------------------------------------

    def cancel_by_passenger(self, session: Session, passenger_id: str, ride_id: str, now: float) -> CancelResult:
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        state_before, rider_id = ride.state, ride.rider_id
        if rider_id is not None and state_before in (RideState.ACCEPTED, RideState.ARRIVED):
            self.lock_queued_ride(session, rider_id)
        result = self.payments.cancel_ride(session, ride_id, now)
        repo.log_ride_event(
            session, ride_id, "cancelled",
            {"by": "passenger", "fee_cents": result.fee_cents, "refund": result.refund_needed},
            now,
        )
        if state_before in (RideState.REQUESTED, RideState.SEARCHING):
            self.dispatcher.withdraw_offer(session, ride_id)
        if rider_id is not None:
            self.events.add(rider_id, "ride_cancelled", {"ride_id": ride_id, "by": "passenger"})
            if state_before in (RideState.ACCEPTED, RideState.ARRIVED):
                self.after_ride_ends(session, rider_id, now)
        return result

    # --- avaliação ------------------------------------------------------------------------------

    def rate(self, session: Session, user_id: str, ride_id: str, stars: int, now: float) -> None:
        if not 1 <= stars <= 5:
            raise ValueError("A nota vai de 1 a 5.")
        ride = repo.get_ride(session, ride_id)
        if ride.state is not RideState.COMPLETED:
            raise InvalidTransition("Só dá para avaliar depois que a corrida acaba.")
        if user_id == ride.passenger_id:
            to_user = ride.rider_id
        elif user_id == ride.rider_id:
            to_user = ride.passenger_id
        else:
            raise NotYourRide("Essa corrida não é sua.")
        try:
            with session.begin_nested():
                session.add(
                    RatingRow(ride_id=ride_id, from_user=user_id, to_user=to_user, stars=stars, created_at=now)
                )
                session.flush()
        except IntegrityError as exc:
            raise AlreadyRated("Você já avaliou esta corrida.") from exc
        if user_id == ride.passenger_id:
            profile = session.get(RiderProfileRow, to_user, with_for_update=True)
            profile.rating_sum += stars
            profile.rating_count += 1
            session.flush()
        repo.log_ride_event(session, ride_id, "rated", {"by": user_id, "stars": stars}, now)
