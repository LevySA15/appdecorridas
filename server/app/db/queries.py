"""Consultas de leitura usadas pelos serviços. Sem regra de negócio, só perguntas ao banco."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RideRow, RiderProfileRow, UserRow
from app.domain.rides import RideState


@dataclass(frozen=True)
class RiderCard:
    """A ficha que o passageiro vê (spec, seção 8): sem selo de permissão da prefeitura."""

    rider_id: str
    name: str
    plate: str
    moto_model: str
    rating: float | None
    rating_count: int
    selfie_key: str | None


def rider_card(session: Session, rider_id: str) -> RiderCard:
    found = session.execute(
        select(RiderProfileRow, UserRow.name)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(RiderProfileRow.user_id == rider_id)
    ).one_or_none()
    if found is None:
        raise LookupError(f"motoqueiro {rider_id} não encontrado")
    profile, name = found
    rating = round(profile.rating_sum / profile.rating_count, 1) if profile.rating_count else None
    return RiderCard(
        rider_id=rider_id, name=name, plate=profile.plate, moto_model=profile.moto_model,
        rating=rating, rating_count=profile.rating_count, selfie_key=profile.selfie_key,
    )



_TERMINAL = (RideState.COMPLETED.value, RideState.CANCELLED.value, RideState.NO_RIDER.value)
_ACTIVE = (RideState.ACCEPTED.value, RideState.ARRIVED.value, RideState.IN_PROGRESS.value)


def passenger_open_ride_id(session: Session, passenger_id: str) -> str | None:
    """Corrida do passageiro que ainda não terminou (procurando, na fila, a caminho ou andando)."""
    return session.execute(
        select(RideRow.id).where(RideRow.passenger_id == passenger_id, RideRow.state.notin_(_TERMINAL)).limit(1)
    ).scalar_one_or_none()


def passenger_unpaid_cash_ride_id(session: Session, passenger_id: str) -> str | None:
    """Corrida em dinheiro já concluída, mas ainda sem pagamento confirmado."""
    return session.execute(
        select(RideRow.id)
        .where(
            RideRow.passenger_id == passenger_id,
            RideRow.state == RideState.COMPLETED.value,
            RideRow.payment_method == "cash",
            RideRow.end_payment_confirmed.is_(False),
        )
        .limit(1)
    ).scalar_one_or_none()


def count_searching_rides(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(RideRow).where(RideRow.state == RideState.SEARCHING.value)
    ).scalar_one()


def free_online_rider_ids(session: Session, rider_ids: list[str]) -> list[str]:
    """Dos motoqueiros dados, os que estão aprovados, disponíveis, sem bloqueio e sem corrida."""
    if not rider_ids:
        return []
    busy = select(RideRow.rider_id).where(
        RideRow.rider_id.in_(rider_ids), RideRow.state.in_((*_ACTIVE, RideState.QUEUED.value))
    )
    stmt = (
        select(RiderProfileRow.user_id)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(
            RiderProfileRow.user_id.in_(rider_ids),
            RiderProfileRow.online.is_(True),
            RiderProfileRow.status == "approved",
            UserRow.is_blocked.is_(False),
            RiderProfileRow.user_id.notin_(busy),
        )
        .order_by(RiderProfileRow.user_id)
    )
    return list(session.execute(stmt).scalars())
