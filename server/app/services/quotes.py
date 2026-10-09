"""Preço mostrado antes do pedido (spec, seção 6) e quem pode pedir."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow, UserRow
from app.domain.geo import GeoPoint
from app.domain.ids import new_id
from app.domain.maps import MapsProvider
from app.domain.pricing import final_price_cents, price_reason, smooth_factor, target_factor
from app.infra.redis_store import FactorStore, PositionStore


class NotAllowed(Exception):
    """O passageiro não pode pedir agora. A mensagem é para ele."""


class QuoteExpired(Exception):
    """O preço não existe, venceu, já foi usado ou é de outra pessoa."""


@dataclass(frozen=True)
class Quote:
    quote_id: str
    price_cents: int
    distance_m: int
    duration_s: int
    factor: float
    reason: str
    expires_at: float
    pickup: GeoPoint
    destination: GeoPoint
    pickup_text: str
    destination_text: str


def passenger_block_reason(session: Session, passenger_id: str) -> str | None:
    user = session.get(UserRow, passenger_id)
    if user is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    if user.is_blocked:
        return "Sua conta está bloqueada. Fale com o suporte."
    if repo.get_passenger_account(session, passenger_id).unpaid_cents > 0 or queries.passenger_unpaid_cash_ride_id(
        session, passenger_id
    ):
        return "Falta pagar a última corrida. Pague para pedir outra moto."
    if queries.passenger_open_ride_id(session, passenger_id):
        return "Você já tem uma corrida em andamento."
    return None


class QuoteService:
    def __init__(
        self, maps: MapsProvider, positions: PositionStore, factors: FactorStore, cfg: AppConfig | None = None
    ) -> None:
        self.maps = maps
        self.positions = positions
        self.factors = factors
        self.cfg = cfg or AppConfig.defaults()

    def create_quote(
        self,
        session: Session,
        passenger_id: str,
        pickup: GeoPoint,
        destination: GeoPoint,
        pickup_text: str,
        destination_text: str,
        now: float,
    ) -> Quote:
        reason_blocked = passenger_block_reason(session, passenger_id)
        if reason_blocked:
            raise NotAllowed(reason_blocked)
        route = self.maps.route(pickup, destination)
        near = self.positions.nearby(
            pickup, self.cfg.dispatch.search_radius_m, now, self.cfg.dispatch.position_max_age_s
        )
        free = len(queries.free_online_rider_ids(session, [rider_id for rider_id, _ in near]))
        pending = queries.count_searching_rides(session)
        state = self.factors.get()
        if state is None or now - state[1] >= self.cfg.pricing.factor_interval_s:
            previous = state[0] if state is not None else 1.0
            factor = smooth_factor(previous, target_factor(pending, free, self.cfg.pricing), self.cfg.pricing)
            self.factors.set(factor, now)
        else:
            factor = state[0]     # o fator é da cidade: muda no máximo uma vez por intervalo, não a cada cotação
        price = final_price_cents(route.distance_m, factor, self.cfg.pricing)
        quote = Quote(
            quote_id=new_id("q"), price_cents=price, distance_m=route.distance_m, duration_s=route.duration_s,
            factor=factor, reason=price_reason(factor), expires_at=now + self.cfg.rides.quote_ttl_s,
            pickup=pickup, destination=destination, pickup_text=pickup_text, destination_text=destination_text,
        )
        session.add(
            QuoteRow(
                id=quote.quote_id, passenger_id=passenger_id,
                pickup_lat=pickup.lat, pickup_lng=pickup.lng, dest_lat=destination.lat, dest_lng=destination.lng,
                pickup_text=pickup_text[:200], dest_text=destination_text[:200],
                distance_m=route.distance_m, duration_s=route.duration_s, price_cents=price,
                factor=factor, reason=quote.reason, created_at=now, expires_at=quote.expires_at,
            )
        )
        session.flush()
        return quote
