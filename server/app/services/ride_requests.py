"""Pedido de corrida: transforma o preço mostrado em uma corrida em procura (spec, seção 5.1)."""
from __future__ import annotations

import secrets
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow
from app.domain.geo import GeoPoint
from app.domain.ids import new_id
from app.domain.rides import Ride, start_search
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteExpired, passenger_block_reason


class OfferDispatcher(Protocol):
    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None: ...


class RideRequestService:
    def __init__(
        self, dispatcher: OfferDispatcher | None, events: EventCollector, cfg: AppConfig | None = None
    ) -> None:
        self.dispatcher = dispatcher
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def request_ride(
        self, session: Session, passenger_id: str, quote_id: str, method: PaymentMethod, now: float
    ) -> Ride:
        quote = session.execute(select(QuoteRow).where(QuoteRow.id == quote_id).with_for_update()).scalar_one_or_none()
        if quote is None or quote.passenger_id != passenger_id or quote.used or now > quote.expires_at:
            raise QuoteExpired("Esse preço não vale mais. Peça de novo.")
        # Trava o passageiro antes de conferir: dois pedidos ao mesmo tempo (duas cotações) esperam um ao outro
        # e o segundo já enxerga a corrida do primeiro.
        repo.get_passenger_account(session, passenger_id, for_update=True)
        blocked = passenger_block_reason(session, passenger_id)
        if blocked:
            raise NotAllowed(blocked)
        ride = Ride(
            ride_id=new_id("ride"), passenger_id=passenger_id, price_cents=quote.price_cents,
            payment_method=method, pin=f"{secrets.randbelow(10000):04d}",
        )
        start_search(ride, now)
        repo.add_ride(session, ride)
        repo.set_ride_details(
            session, ride.ride_id,
            repo.RideDetails(
                pickup=GeoPoint(quote.pickup_lat, quote.pickup_lng),
                destination=GeoPoint(quote.dest_lat, quote.dest_lng),
                pickup_text=quote.pickup_text, destination_text=quote.dest_text,
                distance_m=quote.distance_m, price_factor=quote.factor, price_reason=quote.reason,
            ),
        )
        quote.used = True
        repo.log_ride_event(
            session, ride.ride_id, "requested",
            {"price_cents": ride.price_cents, "method": method.value, "quote_id": quote_id}, now,
        )
        session.flush()
        if self.dispatcher is not None:
            self.dispatcher.offer_next(session, ride.ride_id, now)
        return repo.get_ride(session, ride.ride_id)
