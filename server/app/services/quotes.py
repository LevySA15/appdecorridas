"""Preço mostrado antes do pedido (spec, seção 6) e quem pode pedir."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow, UserRow
from app.domain.geo import GeoPoint, haversine_m
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
    eta_seconds: int | None = None      # estimativa de quando a moto livre mais perto chega; None se não há moto
    nearby_riders: int = 0
    route: tuple[tuple[float, float], ...] = ()


# "Chega em X min" da tela de confirmação: linha reta até a moto livre mais perto, com a rua 30% mais longa,
# a cerca de 25 km/h. É uma estimativa sem custo de mapa; o tempo de verdade vem da procura.
_STREET_FACTOR = 1.3
_ESTIMATED_SPEED_MPS = 7.0


def passenger_block_reason(session: Session, passenger_id: str) -> str | None:
    user = session.get(UserRow, passenger_id)
    if user is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    if user.is_blocked:
        return "Sua conta está bloqueada. Fale com o suporte."
    if repo.get_passenger_account(session, passenger_id).unpaid_cents > 0 or queries.passenger_unpaid_cash_ride_id(
        session, passenger_id
    ):
        if repo.pending_cancel_fee(session, passenger_id) is not None:
            return "Falta pagar a taxa do cancelamento. Pague para pedir outra moto."
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
        straight_m = haversine_m(pickup, destination)
        if straight_m < self.cfg.rides.min_trip_m:
            raise NotAllowed("A origem e o destino estão muito perto. Escolha outro destino.")
        if straight_m > self.cfg.rides.max_trip_m:
            raise NotAllowed("Esse destino é longe demais para uma corrida de moto.")
        route = self.maps.route(pickup, destination)
        near = self.positions.nearby(
            pickup, self.cfg.dispatch.search_radius_m, now, self.cfg.dispatch.position_max_age_s
        )
        free_ids = set(queries.free_online_rider_ids(session, [rider_id for rider_id, _ in near]))
        free = len(free_ids)
        nearest = next((point for rider_id, point in near if rider_id in free_ids), None)
        eta_seconds = None if nearest is None else int(haversine_m(pickup, nearest) * _STREET_FACTOR / _ESTIMATED_SPEED_MPS)
        route_points = tuple((point.lat, point.lng) for point in route.points)
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
            eta_seconds=eta_seconds, nearby_riders=free, route=route_points,
        )
        session.add(
            QuoteRow(
                id=quote.quote_id, passenger_id=passenger_id,
                pickup_lat=pickup.lat, pickup_lng=pickup.lng, dest_lat=destination.lat, dest_lng=destination.lng,
                pickup_text=pickup_text[:200], dest_text=destination_text[:200],
                distance_m=route.distance_m, duration_s=route.duration_s, price_cents=price,
                factor=factor, reason=quote.reason, route=[list(p) for p in route_points],
                created_at=now, expires_at=quote.expires_at,
            )
        )
        session.flush()
        return quote
