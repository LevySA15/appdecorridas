"""Consultas de leitura usadas pelos serviços. Sem regra de negócio, só perguntas ao banco."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import RideOfferRow, RideRow, RiderProfileRow, SafetyAlertRow, UserRow
from app.domain.fees import RiderAccount
from app.domain.geo import GeoPoint
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

    def public(self) -> dict:
        """O que o app do passageiro recebe: a foto vem por endereço (com login), nunca pela chave interna."""
        return {
            "rider_id": self.rider_id, "name": self.name, "plate": self.plate, "moto_model": self.moto_model,
            "rating": self.rating, "rating_count": self.rating_count,
            "photo_url": f"/v1/riders/{self.rider_id}/documents/selfie" if self.selfie_key else None,
        }


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


@dataclass(frozen=True)
class RiderSnapshot:
    rider_id: str
    available: bool                         # aprovado, disponível e sem bloqueio
    account: RiderAccount
    active_ride_id: str | None
    active_destination: GeoPoint | None
    queued_ride_id: str | None


def rider_snapshots(session: Session, rider_ids: list[str]) -> dict[str, RiderSnapshot]:
    if not rider_ids:
        return {}
    profiles = session.execute(
        select(RiderProfileRow, UserRow.is_blocked)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(RiderProfileRow.user_id.in_(rider_ids))
    ).all()
    active = {
        r.rider_id: r
        for r in session.execute(
            select(RideRow).where(RideRow.rider_id.in_(rider_ids), RideRow.state.in_(_ACTIVE))
        ).scalars()
    }
    queued = {
        r.rider_id: r.id
        for r in session.execute(
            select(RideRow).where(RideRow.rider_id.in_(rider_ids), RideRow.state == RideState.QUEUED.value)
        ).scalars()
    }
    snapshots: dict[str, RiderSnapshot] = {}
    for profile, blocked in profiles:
        ride = active.get(profile.user_id)
        snapshots[profile.user_id] = RiderSnapshot(
            rider_id=profile.user_id,
            available=bool(profile.online and profile.status == "approved" and not blocked),
            account=RiderAccount(
                rider_id=profile.user_id, completed_rides=profile.completed_rides, entry_paid=profile.entry_paid,
                cash_debt_cents=profile.cash_debt_cents, debt_reserved_cents=profile.debt_reserved_cents,
            ),
            active_ride_id=ride.id if ride else None,
            active_destination=GeoPoint(ride.dest_lat, ride.dest_lng) if ride and ride.dest_lat is not None else None,
            queued_ride_id=queued.get(profile.user_id),
        )
    return snapshots


def get_pending_offer(session: Session, ride_id: str, *, for_update: bool = False) -> RideOfferRow | None:
    stmt = select(RideOfferRow).where(RideOfferRow.ride_id == ride_id, RideOfferRow.status == "pending")
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def offered_rider_ids(session: Session, ride_id: str) -> set[str]:
    """Quem já recebeu oferta deste pedido (aceitou, recusou ou deixou vencer): não recebe de novo."""
    return set(session.execute(select(RideOfferRow.rider_id).where(RideOfferRow.ride_id == ride_id)).scalars())


def due_offer_ride_ids(session: Session, now: float) -> list[str]:
    return list(
        session.execute(
            select(RideOfferRow.ride_id)
            .where(RideOfferRow.status == "pending", RideOfferRow.expires_at <= now)
            .order_by(RideOfferRow.id)
        ).scalars()
    )


def rider_active_ride_id(session: Session, rider_id: str) -> str | None:
    return session.execute(
        select(RideRow.id).where(RideRow.rider_id == rider_id, RideRow.state.in_(_ACTIVE)).limit(1)
    ).scalar_one_or_none()


def completed_rides_since(session: Session, rider_id: str, since: float) -> int:
    return session.execute(
        select(func.count()).select_from(RideRow).where(
            RideRow.rider_id == rider_id, RideRow.state == RideState.COMPLETED.value, RideRow.completed_at >= since
        )
    ).scalar_one()




def queued_ride_id_of_rider(session: Session, rider_id: str) -> str | None:
    return session.execute(
        select(RideRow.id).where(RideRow.rider_id == rider_id, RideRow.state == RideState.QUEUED.value).limit(1)
    ).scalar_one_or_none()




def pix_window_due_ride_ids(session: Session, now: float, window_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(
                RideRow.payment_method == "pix",
                RideRow.pix_paid.is_(False),
                RideRow.state.in_((RideState.QUEUED.value, RideState.ACCEPTED.value, RideState.ARRIVED.value)),
                RideRow.pix_charge_created_at <= now - window_s,
            )
            .order_by(RideRow.id)
        ).scalars()
    )


def searching_ride_ids(session: Session) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id).where(RideRow.state == RideState.SEARCHING.value).order_by(RideRow.searching_since)
        ).scalars()
    )


def queued_ride_ids_due(session: Session, now: float, max_wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(RideRow.state == RideState.QUEUED.value, RideRow.queued_since <= now - max_wait_s)
            .order_by(RideRow.id)
        ).scalars()
    )


def arrived_ride_ids_due(session: Session, now: float, max_wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(RideRow.state == RideState.ARRIVED.value, RideRow.arrived_at <= now - max_wait_s)
            .order_by(RideRow.id)
        ).scalars()
    )


def cash_unpaid_ride_ids_due(session: Session, now: float, wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(
                RideRow.state == RideState.COMPLETED.value,
                RideRow.payment_method == "cash",
                RideRow.end_payment_confirmed.is_(False),
                RideRow.non_payment_reported.is_(False),
                RideRow.completed_at <= now - wait_s,
            )
            .order_by(RideRow.id)
        ).scalars()
    )


def cash_rides_without_charge_ids(session: Session) -> list[str]:
    """Corridas em dinheiro concluídas, ainda sem pagamento confirmado e sem QR (provedor estava fora)."""
    return list(
        session.execute(
            select(RideRow.id)
            .where(
                RideRow.state == RideState.COMPLETED.value,
                RideRow.payment_method == "cash",
                RideRow.end_payment_confirmed.is_(False),
                RideRow.current_charge_id.is_(None),
            )
            .order_by(RideRow.id)
        ).scalars()
    )


@dataclass(frozen=True)
class RiderListItem:
    rider_id: str
    name: str
    phone: str
    cpf: str
    plate: str
    moto_model: str
    status: str
    reason: str | None
    cnh_expires_on: object
    crlv_expires_on: object
    documents: tuple[str, ...]          # quais fotos existem: selfie, cnh, crlv


def list_riders(session: Session, status: str, limit: int, offset: int) -> list[RiderListItem]:
    rows = session.execute(
        select(RiderProfileRow, UserRow)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(RiderProfileRow.status == status)
        .order_by(UserRow.created_at, RiderProfileRow.user_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        RiderListItem(
            rider_id=p.user_id, name=u.name, phone=u.phone, cpf=p.cpf, plate=p.plate, moto_model=p.moto_model,
            status=p.status, reason=p.rejected_reason, cnh_expires_on=p.cnh_expires_on,
            crlv_expires_on=p.crlv_expires_on,
            documents=tuple(
                kind for kind, key in (("selfie", p.selfie_key), ("cnh", p.cnh_photo_key), ("crlv", p.crlv_key)) if key
            ),
        )
        for p, u in rows
    ]


def rider_document_key(session: Session, rider_id: str, kind: str) -> str | None:
    column = {"selfie": RiderProfileRow.selfie_key, "cnh": RiderProfileRow.cnh_photo_key, "crlv": RiderProfileRow.crlv_key}[kind]
    return session.execute(select(column).where(RiderProfileRow.user_id == rider_id)).scalar_one_or_none()


def passenger_rode_with(session: Session, passenger_id: str, rider_id: str) -> bool:
    """O passageiro tem (ou teve) uma corrida aceita por este motoqueiro. Dá o direito de ver a selfie dele."""
    return session.execute(
        select(RideRow.id)
        .where(
            RideRow.passenger_id == passenger_id,
            RideRow.rider_id == rider_id,
            RideRow.state.notin_((RideState.CANCELLED.value, RideState.NO_RIDER.value)),
        )
        .limit(1)
    ).first() is not None


def pending_offer_for_rider(session: Session, rider_id: str) -> RideOfferRow | None:
    return session.execute(
        select(RideOfferRow).where(RideOfferRow.rider_id == rider_id, RideOfferRow.status == "pending")
    ).scalar_one_or_none()


def rider_unpaid_cash_ride_id(session: Session, rider_id: str) -> str | None:
    """A corrida em dinheiro mais recente que o motoqueiro terminou e ainda está sem pagamento confirmado."""
    return session.execute(
        select(RideRow.id)
        .where(
            RideRow.rider_id == rider_id,
            RideRow.state == RideState.COMPLETED.value,
            RideRow.payment_method == "cash",
            RideRow.end_payment_confirmed.is_(False),
        )
        .order_by(RideRow.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


@dataclass(frozen=True)
class RiderContext:
    online: bool
    ride_id: str | None
    passenger_id: str | None
    ride_state: str | None


def rider_context(session: Session, rider_id: str) -> RiderContext | None:
    """O que o servidor precisa saber a cada posição recebida: está disponível? tem corrida em andamento?"""
    online = session.execute(
        select(RiderProfileRow.online).where(RiderProfileRow.user_id == rider_id)
    ).scalar_one_or_none()
    if online is None:
        return None
    ride = session.execute(
        select(RideRow.id, RideRow.passenger_id, RideRow.state)
        .where(RideRow.rider_id == rider_id, RideRow.state.in_(_ACTIVE))
        .limit(1)
    ).first()
    return RiderContext(bool(online), *(tuple(ride) if ride else (None, None, None)))


def admin_ids(session: Session) -> list[str]:
    """Quem recebe os avisos de segurança: todos os administradores sem bloqueio."""
    return list(
        session.execute(
            select(UserRow.id).where(UserRow.role == "admin", UserRow.is_blocked.is_(False)).order_by(UserRow.id)
        ).scalars()
    )


@dataclass(frozen=True)
class SafetyAlertItem:
    alert_id: int
    ride_id: str
    kind: str
    status: str
    suspected_mock: bool
    lat: float | None
    lng: float | None
    created_at: float
    answered_at: float | None
    resolved_at: float | None
    note: str | None
    passenger_name: str
    rider_name: str
    plate: str


def list_safety_alerts(session: Session, status: str, limit: int, offset: int) -> list[SafetyAlertItem]:
    passenger, rider = aliased(UserRow), aliased(UserRow)
    rows = session.execute(
        select(SafetyAlertRow, passenger.name, rider.name, RiderProfileRow.plate)
        .join(RideRow, RideRow.id == SafetyAlertRow.ride_id)
        .join(passenger, passenger.id == RideRow.passenger_id)
        .join(rider, rider.id == RideRow.rider_id)
        .join(RiderProfileRow, RiderProfileRow.user_id == RideRow.rider_id)
        .where(SafetyAlertRow.status == status)
        .order_by(SafetyAlertRow.created_at.desc(), SafetyAlertRow.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        SafetyAlertItem(
            a.id, a.ride_id, a.kind, a.status, a.suspected_mock, a.lat, a.lng, a.created_at, a.answered_at,
            a.resolved_at, a.note, passenger_name, rider_name, plate,
        )
        for a, passenger_name, rider_name, plate in rows
    ]


def queue_info(session: Session, ride_id: str, rider_id: str) -> dict:
    """Para o passageiro da fila: onde a moto termina a corrida de agora e em quanto tempo chega até ele."""
    active_id = rider_active_ride_id(session, rider_id)
    finishing_at = None
    if active_id is not None:
        finishing_at = session.execute(select(RideRow.dest_text).where(RideRow.id == active_id)).scalar_one_or_none()
    eta = session.execute(
        select(RideOfferRow.eta_seconds).where(RideOfferRow.ride_id == ride_id, RideOfferRow.status == "accepted")
    ).scalar_one_or_none()
    return {"finishing_at": finishing_at or "", "eta_seconds": eta}
