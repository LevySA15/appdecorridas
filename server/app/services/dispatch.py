"""Procura da moto e ofertas, uma por vez (spec, seções 5.1, 5.2 e 12)."""
from __future__ import annotations

import dataclasses
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RideOfferRow
from app.domain.clock import local_day_start
from app.domain.dispatch import RiderStatus, rank_candidates
from app.domain.fees import can_receive_cash_offers, fee_for_ride, offer_block_reason
from app.domain.geo import haversine_m
from app.domain.maps import MapsProvider
from app.domain.rides import Ride, RideState, accept, mark_no_rider
from app.domain.types import PaymentMethod
from app.infra.redis_store import PositionStore
from app.services.events import EventCollector
from app.services.payments import PaymentService


# Moto na cidade não passa de ~54 km/h por muito tempo: quem está mais longe do destino do que isso em
# `finishing_max_s` segundos não pode estar "terminando", então nem vale pagar por uma rota.
_MAX_PLAUSIBLE_SPEED_MPS = 15.0


def distance_to_pickup_m(
    session: Session, positions: PositionStore, ride_id: str, rider_id: str, now: float, max_age_s: float
) -> float | None:
    """Distância em linha reta da moto ao ponto de embarque; `None` sem posição ou com posição mais velha que `max_age_s`."""
    seen = positions.last_seen(rider_id)
    point = positions.get(rider_id)
    if point is None or seen is None or now - seen > max_age_s:
        return None
    try:
        pickup = repo.get_ride_details(session, ride_id).pickup
    except LookupError:
        return None
    return haversine_m(point, pickup)


class OfferGone(Exception):
    """A oferta não existe mais para este motoqueiro (venceu, foi para outro, ou a corrida mudou)."""


def offer_payload(
    ride: Ride, details: repo.RideDetails, *, eta_seconds: int | None, will_queue: bool, expires_at: float
) -> dict:
    """O que o motoqueiro vê numa oferta. Serve ao aviso em tempo real e ao estado que o app pede ao reconectar."""
    return {
        "ride_id": ride.ride_id, "price_cents": ride.price_cents, "payment_method": ride.payment_method.value,
        "pickup": {"lat": details.pickup.lat, "lng": details.pickup.lng, "text": details.pickup_text},
        "destination": {"lat": details.destination.lat, "lng": details.destination.lng, "text": details.destination_text},
        "distance_m": details.distance_m, "seconds_to_pickup": eta_seconds,
        "will_queue": will_queue, "expires_at": expires_at,
    }


class Reservations(Protocol):
    def reserve(self, rider_id: str, ride_id: str) -> bool: ...

    def release(self, rider_id: str, ride_id: str) -> None: ...


class DispatchService:
    def __init__(
        self,
        positions: PositionStore,
        reservations: Reservations,
        maps: MapsProvider,
        payments: PaymentService,
        events: EventCollector,
        cfg: AppConfig | None = None,
    ) -> None:
        self.positions = positions
        self.reservations = reservations
        self.maps = maps
        self.payments = payments
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    # --- procura ---------------------------------------------------------------------

    def _statuses(self, session: Session, ride: Ride, near: list, declined: set[str]) -> list[RiderStatus]:
        """Motos que podem receber este pedido. Só pede rota (que custa) de quem pode estar terminando."""
        snapshots = queries.rider_snapshots(session, [rider_id for rider_id, _ in near])
        finish_bound_m = self.cfg.dispatch.finishing_max_s * _MAX_PLAUSIBLE_SPEED_MPS
        statuses: list[RiderStatus] = []
        for rider_id, point in near:
            snap = snapshots.get(rider_id)
            if snap is None or not snap.available or rider_id in declined or snap.queued_ride_id is not None:
                continue
            busy = snap.active_ride_id is not None
            # a corrida que ele está fazendo conta para a entrada: a 10ª corrida em andamento já fecha o teste
            gate = dataclasses.replace(snap.account, completed_rides=snap.account.completed_rides + (1 if busy else 0))
            if offer_block_reason(gate, self.cfg.fees) is not None:
                continue
            if ride.payment_method is PaymentMethod.CASH and not can_receive_cash_offers(gate, self.cfg.fees):
                continue
            seconds = None
            if busy and snap.active_destination and haversine_m(point, snap.active_destination) <= finish_bound_m:
                seconds = self.maps.eta_seconds(point, snap.active_destination)
            statuses.append(
                RiderStatus(
                    rider_id, point, True, snap.active_ride_id, snap.queued_ride_id, seconds, snap.active_destination
                )
            )
        return statuses

    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None:
        """Oferece o pedido à próxima moto. Devolve o motoqueiro com oferta pendente, ou None."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.SEARCHING:
            return None
        pending = queries.get_pending_offer(session, ride_id, for_update=True)
        if pending is not None:
            if pending.expires_at > now:
                return pending.rider_id
            pending.status = "expired"
            session.flush()
            self.reservations.release(pending.rider_id, ride_id)
            self.events.add(pending.rider_id, "offer_expired", {"ride_id": ride_id})
        details = repo.get_ride_details(session, ride_id)
        dispatch_cfg = self.cfg.dispatch
        near = self.positions.nearby(details.pickup, dispatch_cfg.search_radius_m, now, dispatch_cfg.position_max_age_s)
        declined = queries.offered_rider_ids(session, ride_id)
        statuses = self._statuses(session, ride, near, declined)
        for candidate in rank_candidates(statuses, details.pickup, self.maps, dispatch_cfg):
            if not self.reservations.reserve(candidate.rider_id, ride_id):
                continue
            try:
                with session.begin_nested():
                    session.add(
                        RideOfferRow(
                            ride_id=ride_id, rider_id=candidate.rider_id, status="pending",
                            will_queue=candidate.will_queue, eta_seconds=candidate.eta_seconds, created_at=now,
                            expires_at=now + dispatch_cfg.offer_timeout_s,
                        )
                    )
                    session.flush()
            except IntegrityError:
                self.reservations.release(candidate.rider_id, ride_id)
                continue
            repo.log_ride_event(session, ride_id, "offered", {"rider_id": candidate.rider_id}, now)
            self.events.add(
                candidate.rider_id, "offer",
                offer_payload(
                    ride, details, eta_seconds=candidate.eta_seconds, will_queue=candidate.will_queue,
                    expires_at=now + dispatch_cfg.offer_timeout_s,
                ),
            )
            return candidate.rider_id
        return None

    # --- resposta do motoqueiro ----------------------------------------------------------

    def accept_offer(self, session: Session, rider_id: str, ride_id: str, now: float) -> Ride:
        ride = repo.get_ride(session, ride_id, for_update=True)
        offer = queries.get_pending_offer(session, ride_id, for_update=True)
        if (
            ride.state is not RideState.SEARCHING
            or offer is None
            or offer.rider_id != rider_id
            or offer.expires_at <= now
        ):
            raise OfferGone("Essa corrida já foi para outro motoqueiro.")
        snapshot = queries.rider_snapshots(session, [rider_id]).get(rider_id)
        if snapshot is None or not snapshot.available:      # parou, foi bloqueado ou perdeu a aprovação depois da oferta
            raise OfferGone("Você não está disponível para essa corrida.")
        account = repo.get_rider_account(session, rider_id, for_update=True)
        if offer_block_reason(account, self.cfg.fees) == "divida_pendente":     # ficou devendo depois de receber a oferta
            raise OfferGone("Você tem uma taxa para pagar e não pode aceitar corridas agora.")
        busy = queries.rider_active_ride_id(session, rider_id) is not None
        number = queries.completed_rides_since(session, rider_id, local_day_start(now)) + (1 if busy else 0) + 1
        fee = fee_for_ride(number, self.cfg.fees)
        accept(ride, rider_id, now, rider_busy=busy)
        ride.fee_cents = fee
        if not busy:        # a moto começa a vir agora; na fila isso só acontece quando ela for promovida
            ride.approach_start_m = distance_to_pickup_m(
                session, self.positions, ride_id, rider_id, now, self.cfg.dispatch.position_max_age_s
            )
        repo.save_ride(session, ride)
        offer.status = "accepted"
        session.flush()
        self.reservations.release(rider_id, ride_id)
        charge = self.payments.start_pix_charge(session, ride_id, fee) if ride.payment_method is PaymentMethod.PIX else None
        repo.log_ride_event(session, ride_id, "accepted", {"rider_id": rider_id, "queued": busy, "fee_cents": fee}, now)
        card = queries.rider_card(session, rider_id)
        self.events.add(rider_id, "ride_assigned", {"ride_id": ride_id, "queued": busy})
        self.events.add(
            ride.passenger_id, "rider_accepted",
            {
                "ride_id": ride_id, "queued": busy, "pin": ride.pin,
                "queue": queries.queue_info(session, ride_id, rider_id) if busy else None,
                "rider": card.public(),
                "pay": None if charge is None else {
                    "charge_id": charge.charge_id, "amount_cents": charge.amount_cents,
                    "expires_at": now + self.cfg.rides.pix_window_s,
                },
            },
        )
        return repo.get_ride(session, ride_id)

    def decline_offer(self, session: Session, rider_id: str, ride_id: str, now: float) -> str | None:
        repo.get_ride(session, ride_id, for_update=True)
        offer = queries.get_pending_offer(session, ride_id, for_update=True)
        if offer is None or offer.rider_id != rider_id:
            raise OfferGone("Essa corrida já foi para outro motoqueiro.")
        offer.status = "declined"
        session.flush()
        self.reservations.release(rider_id, ride_id)
        repo.log_ride_event(session, ride_id, "declined", {"rider_id": rider_id}, now)
        return self.offer_next(session, ride_id, now)

    def withdraw_offer(self, session: Session, ride_id: str) -> None:
        """A corrida saiu da procura (por exemplo, o passageiro cancelou): tira a oferta e solta a moto."""
        pending = queries.get_pending_offer(session, ride_id, for_update=True)
        if pending is None:
            return
        pending.status = "expired"
        session.flush()
        self.reservations.release(pending.rider_id, ride_id)
        self.events.add(pending.rider_id, "offer_expired", {"ride_id": ride_id})

    def give_up_if_expired(self, session: Session, ride_id: str, now: float) -> bool:
        """Passaram `search_give_up_s` sem moto e sem oferta pendente: a corrida fica sem motoqueiro."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.SEARCHING or queries.get_pending_offer(session, ride_id) is not None:
            return False
        if ride.searching_since is None or now - ride.searching_since < self.cfg.rides.search_give_up_s:
            return False
        mark_no_rider(ride, now, self.cfg.rides)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "no_rider", {}, now)
        self.events.add(ride.passenger_id, "no_rider", {"ride_id": ride_id})
        return True

    def expire_offers(self, session: Session, now: float) -> int:
        """Ofertas que passaram dos 15 segundos: expira e oferece à próxima moto. Devolve quantas venceram."""
        due = queries.due_offer_ride_ids(session, now)
        for ride_id in due:
            self.offer_next(session, ride_id, now)
        return len(due)
