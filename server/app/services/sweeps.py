"""Tarefas de tempo, rodadas de poucos em poucos segundos pelo servidor (spec, seções 5 e 12).

Cada corrida é tratada num ponto de salvamento: se uma falhar, o banco volta ao que era, os avisos
anotados naquela corrida são descartados, o erro vai para o relatório e as outras seguem. Os serviços
e este precisam compartilhar o mesmo `EventCollector`. Quem chama faz o commit (ou o rollback) do conjunto.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.domain.rides import arrival_wait_expired, queue_wait_expired
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.trips import TripService


@dataclass
class SweepReport:
    offers_expired: int = 0
    pix_expired: int = 0
    queue_released: int = 0
    arrival_cancelled: int = 0
    cash_blocked: int = 0
    qr_created: int = 0
    searches_given_up: int = 0
    errors: list[str] = field(default_factory=list)


class SweepService:
    def __init__(
        self,
        payments: PaymentService,
        dispatcher: DispatchService,
        trips: TripService,
        events: EventCollector,
        cfg: AppConfig | None = None,
    ) -> None:
        self.payments = payments
        self.dispatcher = dispatcher
        self.trips = trips
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def _each(
        self, session: Session, report: SweepReport, label: str, ride_ids: list[str], action: Callable[[str], bool]
    ) -> int:
        done = 0
        for ride_id in ride_ids:
            mark = self.events.mark()
            try:
                with session.begin_nested():
                    if action(ride_id):
                        done += 1
            except Exception as exc:  # um pedido com problema não pode travar os outros
                self.events.rollback_to(mark)   # os avisos desta corrida somem junto com o banco
                report.errors.append(f"{label} {ride_id}: {exc}")
        return done

    def run(self, session: Session, now: float) -> SweepReport:
        report = SweepReport()
        rides = self.cfg.rides

        def offers(ride_id: str) -> bool:
            self.dispatcher.offer_next(session, ride_id, now)
            return True

        def pix(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id, for_update=True)
            if ride.rider_id is not None:
                self.trips.lock_queued_ride(session, ride.rider_id)
            if not self.payments.expire_unpaid_pix(session, ride_id, now):
                return False
            repo.log_ride_event(session, ride_id, "cancelled", {"by": "timeout", "reason": "pix_expired"}, now)
            self.events.add(ride.passenger_id, "ride_cancelled", {"ride_id": ride_id, "reason": "pix_expired"})
            if ride.rider_id is not None:
                self.events.add(ride.rider_id, "ride_cancelled", {"ride_id": ride_id, "reason": "pix_expired"})
                self.trips.after_ride_ends(session, ride.rider_id, now)
            return True

        def queue(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id)
            if not queue_wait_expired(ride, now, rides):
                return False
            refunded = self.payments.release_queued_ride(session, ride_id, now)
            repo.log_ride_event(
                session, ride_id, "queue_released", {"reason": "queue_timeout", "refunded": refunded}, now
            )
            self.events.add(ride.passenger_id, "queue_released", {"ride_id": ride_id, "refunded": refunded})
            self.dispatcher.offer_next(session, ride_id, now)
            return True

        def arrival(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id, for_update=True)
            if not arrival_wait_expired(ride, now, rides):
                return False
            if ride.rider_id is not None:
                self.trips.lock_queued_ride(session, ride.rider_id)
            result = self.payments.cancel_after_arrival_timeout(session, ride_id, now)
            repo.log_ride_event(
                session, ride_id, "cancelled",
                {"by": "timeout", "reason": "arrival_wait",
                 "compensation_cents": result.compensation_cents, "refund": result.refund_needed},
                now,
            )
            self.events.add(ride.passenger_id, "ride_cancelled", {"ride_id": ride_id, "reason": "arrival_wait"})
            if ride.rider_id is not None:
                self.events.add(ride.rider_id, "ride_cancelled", {"ride_id": ride_id, "reason": "arrival_wait"})
                self.trips.after_ride_ends(session, ride.rider_id, now)
            return True

        def qr(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id, for_update=True)
            charge = self.payments.start_end_charge(session, ride_id, ride.fee_cents or 0)
            repo.log_ride_event(session, ride_id, "qr_created", {}, now)
            payload = {"ride_id": ride_id, "charge_id": charge.charge_id, "amount_cents": charge.amount_cents}
            self.events.add(ride.passenger_id, "qr_ready", payload)
            if ride.rider_id is not None:
                self.events.add(ride.rider_id, "qr_ready", payload)
            return True

        def cash(ride_id: str) -> bool:
            return self.payments.block_unpaid_cash_ride(session, ride_id, now)

        def searching(ride_id: str) -> bool:
            if self.dispatcher.offer_next(session, ride_id, now) is not None:
                return False
            return self.dispatcher.give_up_if_expired(session, ride_id, now)

        report.offers_expired = self._each(session, report, "oferta", queries.due_offer_ride_ids(session, now), offers)
        report.pix_expired = self._each(
            session, report, "pix", queries.pix_window_due_ride_ids(session, now, rides.pix_window_s), pix
        )
        report.queue_released = self._each(
            session, report, "fila", queries.queued_ride_ids_due(session, now, rides.queue_max_wait_s), queue
        )
        report.arrival_cancelled = self._each(
            session, report, "chegada", queries.arrived_ride_ids_due(session, now, rides.max_wait_at_arrival_s), arrival
        )
        report.qr_created = self._each(
            session, report, "qr", queries.cash_rides_without_charge_ids(session), qr
        )
        report.cash_blocked = self._each(
            session, report, "dinheiro", queries.cash_unpaid_ride_ids_due(session, now, rides.cash_pay_wait_s), cash
        )
        report.searches_given_up = self._each(
            session, report, "procura", queries.searching_ride_ids(session), searching
        )
        return report
