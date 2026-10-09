"""Consultas de leitura usadas pelos serviços. Sem regra de negócio, só perguntas ao banco."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RiderProfileRow, UserRow


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
