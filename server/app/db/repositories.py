"""Leitura e gravação dos objetos do domínio no PostgreSQL.

Nenhuma função faz commit: quem chama controla a transação. Quando uma operação precisa travar
várias linhas, a ordem é sempre corrida, motoqueiro, cobrança (evita impasse entre transações).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    CancelFeeRow,
    PassengerProfileRow,
    PixChargeRow,
    ProcessedEventRow,
    RideEventRow,
    RideRow,
    RiderProfileRow,
    UserRow,
)
from app.domain.balance import CancelFee
from app.domain.fees import RiderAccount
from app.domain.geo import GeoPoint
from app.domain.payments import DebtState, PixCharge, Split
from app.domain.rides import PassengerAccount, Ride, RideState
from app.domain.types import PaymentMethod


def _locking(stmt: Select, for_update: bool) -> Select:
    if for_update:
        return stmt.with_for_update().execution_options(populate_existing=True)
    return stmt


# --- pessoas -----------------------------------------------------------------


def add_user(session: Session, *, user_id: str, phone: str, name: str, role: str) -> None:
    session.add(UserRow(id=user_id, phone=phone, name=name, role=role))
    session.flush()


def add_rider_profile(
    session: Session,
    *,
    user_id: str,
    cpf: str,
    cnh_number: str,
    plate: str,
    moto_model: str,
    status: str = "pending",
) -> None:
    session.add(
        RiderProfileRow(
            user_id=user_id, cpf=cpf, cnh_number=cnh_number, plate=plate,
            moto_model=moto_model, status=status,
        )
    )
    session.flush()


def get_rider_account(session: Session, rider_id: str, *, for_update: bool = False) -> RiderAccount:
    stmt = _locking(select(RiderProfileRow).where(RiderProfileRow.user_id == rider_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"motoqueiro {rider_id} não encontrado")
    return RiderAccount(
        rider_id=row.user_id,
        completed_rides=row.completed_rides,
        entry_paid=row.entry_paid,
        cash_debt_cents=row.cash_debt_cents,
        debt_reserved_cents=row.debt_reserved_cents,
    )


def save_rider_account(session: Session, acc: RiderAccount) -> None:
    row = session.get(RiderProfileRow, acc.rider_id)
    if row is None:
        raise LookupError(f"motoqueiro {acc.rider_id} não encontrado")
    row.completed_rides = acc.completed_rides
    row.entry_paid = acc.entry_paid
    row.cash_debt_cents = acc.cash_debt_cents
    row.debt_reserved_cents = acc.debt_reserved_cents
    session.flush()


def add_passenger_profile(session: Session, *, user_id: str) -> None:
    session.add(PassengerProfileRow(user_id=user_id))
    session.flush()


def get_passenger_account(
    session: Session, passenger_id: str, *, for_update: bool = False
) -> PassengerAccount:
    stmt = _locking(
        select(PassengerProfileRow).where(PassengerProfileRow.user_id == passenger_id), for_update
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    return PassengerAccount(passenger_id=row.user_id, unpaid_cents=row.unpaid_cents, balance_cents=row.balance_cents)


def save_passenger_account(session: Session, acc: PassengerAccount) -> None:
    row = session.get(PassengerProfileRow, acc.passenger_id)
    if row is None:
        raise LookupError(f"passageiro {acc.passenger_id} não encontrado")
    row.unpaid_cents = acc.unpaid_cents
    row.balance_cents = acc.balance_cents
    session.flush()


@dataclass(frozen=True)
class EmergencyContact:
    name: str
    phone: str


def get_emergency_contact(session: Session, passenger_id: str) -> EmergencyContact | None:
    row = session.get(PassengerProfileRow, passenger_id)
    if row is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    if not row.emergency_phone:
        return None
    return EmergencyContact(row.emergency_name or "", row.emergency_phone)


def set_emergency_contact(session: Session, passenger_id: str, name: str, phone: str) -> None:
    row = session.get(PassengerProfileRow, passenger_id)
    if row is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    row.emergency_name, row.emergency_phone = name, phone
    session.flush()


# --- corridas ----------------------------------------------------------------


def _ride_to_domain(row: RideRow) -> Ride:
    return Ride(
        ride_id=row.id,
        passenger_id=row.passenger_id,
        price_cents=row.price_cents,
        payment_method=PaymentMethod(row.payment_method),
        pin=row.pin,
        state=RideState(row.state),
        rider_id=row.rider_id,
        helmet_confirmed=row.helmet_confirmed,
        pix_paid=row.pix_paid,
        pix_charge_created_at=row.pix_charge_created_at,
        searching_since=row.searching_since,
        queued_since=row.queued_since,
        en_route_since=row.en_route_since,
        arrived_at=row.arrived_at,
        end_payment_confirmed=row.end_payment_confirmed,
        non_payment_reported=row.non_payment_reported,
        completed_at=row.completed_at,
        fee_cents=row.fee_cents,
        approach_start_m=row.approach_start_m,
    )


def _apply_ride(row: RideRow, ride: Ride) -> None:
    row.passenger_id = ride.passenger_id
    row.rider_id = ride.rider_id
    row.price_cents = ride.price_cents
    row.payment_method = ride.payment_method.value
    row.pin = ride.pin
    row.state = ride.state.value
    row.helmet_confirmed = ride.helmet_confirmed
    row.pix_paid = ride.pix_paid
    row.pix_charge_created_at = ride.pix_charge_created_at
    row.searching_since = ride.searching_since
    row.queued_since = ride.queued_since
    row.en_route_since = ride.en_route_since
    row.arrived_at = ride.arrived_at
    row.end_payment_confirmed = ride.end_payment_confirmed
    row.non_payment_reported = ride.non_payment_reported
    row.completed_at = ride.completed_at
    row.fee_cents = ride.fee_cents
    row.approach_start_m = ride.approach_start_m


def add_ride(session: Session, ride: Ride) -> None:
    row = RideRow(id=ride.ride_id)
    _apply_ride(row, ride)
    session.add(row)
    session.flush()


def get_ride(session: Session, ride_id: str, *, for_update: bool = False) -> Ride:
    stmt = _locking(select(RideRow).where(RideRow.id == ride_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    return _ride_to_domain(row)


def save_ride(session: Session, ride: Ride) -> None:
    row = session.get(RideRow, ride.ride_id)
    if row is None:
        raise LookupError(f"corrida {ride.ride_id} não encontrada")
    _apply_ride(row, ride)
    session.flush()


def set_current_charge(session: Session, ride_id: str, charge_id: str | None) -> None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    row.current_charge_id = charge_id
    session.flush()


def get_current_charge_id(session: Session, ride_id: str) -> str | None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    return row.current_charge_id


# --- cobranças e eventos --------------------------------------------------------


def _charge_to_domain(row: PixChargeRow) -> PixCharge:
    return PixCharge(
        charge_id=row.charge_id,
        ride_id=row.ride_id or "",
        rider_id=row.rider_id or "",
        amount_cents=row.amount_cents,
        split=Split(
            rider_cents=row.rider_cents,
            company_cents=row.company_cents,
            debt_paid_cents=row.debt_paid_cents,
        ),
        paid=row.paid,
        refunded=row.refunded,
        debt_state=DebtState(row.debt_state),
        purpose=row.purpose,
        br_code=row.br_code,
        passenger_id=row.passenger_id or "",
    )


def _apply_charge(row: PixChargeRow, charge: PixCharge) -> None:
    row.ride_id = charge.ride_id or None
    row.rider_id = charge.rider_id or None
    row.passenger_id = charge.passenger_id or None
    row.amount_cents = charge.amount_cents
    row.rider_cents = charge.split.rider_cents
    row.company_cents = charge.split.company_cents
    row.debt_paid_cents = charge.split.debt_paid_cents
    row.paid = charge.paid
    row.refunded = charge.refunded
    row.debt_state = charge.debt_state.value
    row.purpose = charge.purpose
    row.br_code = charge.br_code


def add_charge(session: Session, charge: PixCharge) -> None:
    row = PixChargeRow(charge_id=charge.charge_id)
    _apply_charge(row, charge)
    session.add(row)
    session.flush()


def get_charge(session: Session, charge_id: str, *, for_update: bool = False) -> PixCharge:
    stmt = _locking(select(PixChargeRow).where(PixChargeRow.charge_id == charge_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"cobrança {charge_id} não encontrada")
    return _charge_to_domain(row)


def save_charge(session: Session, charge: PixCharge) -> None:
    row = session.get(PixChargeRow, charge.charge_id)
    if row is None:
        raise LookupError(f"cobrança {charge.charge_id} não encontrada")
    _apply_charge(row, charge)
    session.flush()


def first_time_event(session: Session, event_id: str) -> bool:
    """Grava o aviso do provedor. Devolve True se ele nunca tinha sido visto (chave única no banco)."""
    stmt = (
        pg_insert(ProcessedEventRow)
        .values(event_id=event_id)
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(ProcessedEventRow.event_id)
    )
    return session.execute(stmt).scalar_one_or_none() is not None



# --- detalhes da corrida e eventos ---------------------------------------------------


@dataclass(frozen=True)
class RideDetails:
    pickup: GeoPoint
    destination: GeoPoint
    pickup_text: str
    destination_text: str
    distance_m: int
    price_factor: float
    price_reason: str
    route: tuple[tuple[float, float], ...] = ()     # pontos (lat, lng) do trajeto, vindos do mapa na hora do preço


def set_ride_details(session: Session, ride_id: str, details: RideDetails) -> None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    row.pickup_lat, row.pickup_lng = details.pickup.lat, details.pickup.lng
    row.dest_lat, row.dest_lng = details.destination.lat, details.destination.lng
    row.pickup_text, row.dest_text = details.pickup_text, details.destination_text
    row.distance_m, row.price_factor, row.price_reason = details.distance_m, details.price_factor, details.price_reason
    row.route = [list(point) for point in details.route] or None
    session.flush()


def get_ride_details(session: Session, ride_id: str) -> RideDetails:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    if row.pickup_lat is None or row.dest_lat is None:
        raise LookupError(f"corrida {ride_id} sem detalhes de trajeto")
    return RideDetails(
        pickup=GeoPoint(row.pickup_lat, row.pickup_lng),
        destination=GeoPoint(row.dest_lat, row.dest_lng),
        pickup_text=row.pickup_text or "",
        destination_text=row.dest_text or "",
        distance_m=row.distance_m or 0,
        price_factor=row.price_factor if row.price_factor is not None else 1.0,
        price_reason=row.price_reason or "",
        route=tuple((float(lat), float(lng)) for lat, lng in (row.route or ())),
    )


def log_ride_event(session: Session, ride_id: str, kind: str, data: dict | None, now: float) -> None:
    session.add(RideEventRow(ride_id=ride_id, kind=kind, data=data or {}, created_at=now))
    session.flush()


def ride_events(session: Session, ride_id: str) -> list[tuple[str, dict]]:
    rows = session.execute(
        select(RideEventRow).where(RideEventRow.ride_id == ride_id).order_by(RideEventRow.id)
    ).scalars()
    return [(r.kind, r.data) for r in rows]




def find_open_entry_charge(session: Session, rider_id: str) -> PixCharge | None:
    """Cobrança da entrada de R$ 50 que o motoqueiro ainda não pagou, se houver."""
    row = session.execute(
        select(PixChargeRow)
        .where(PixChargeRow.rider_id == rider_id, PixChargeRow.purpose == "entry", PixChargeRow.paid.is_(False))
        .limit(1)
    ).scalar_one_or_none()
    return _charge_to_domain(row) if row is not None else None


def ride_event_time(session: Session, ride_id: str, kind: str) -> float | None:
    """Instante do último evento deste tipo na corrida, ou None."""
    return session.execute(
        select(func.max(RideEventRow.created_at)).where(RideEventRow.ride_id == ride_id, RideEventRow.kind == kind)
    ).scalar_one()

# --- taxa de cancelamento tardio ----------------------------------------------------------


def _fee_to_domain(row: CancelFeeRow) -> CancelFee:
    return CancelFee(
        ride_id=row.ride_id, passenger_id=row.passenger_id, rider_id=row.rider_id, fee_cents=row.fee_cents,
        reason=row.reason, created_at=row.created_at, progress=row.progress,
        from_balance_cents=row.from_balance_cents, retained_cents=row.retained_cents,
        pending_cents=row.pending_cents, paid_later_cents=row.paid_later_cents, waived_cents=row.waived_cents,
        credited_back_cents=row.credited_back_cents, appeal_state=row.appeal_state, appeal_text=row.appeal_text,
        appealed_at=row.appealed_at, decided_at=row.decided_at, decided_by=row.decided_by,
        decision_note=row.decision_note,
    )


def _apply_fee(row: CancelFeeRow, fee: CancelFee) -> None:
    row.passenger_id = fee.passenger_id
    row.rider_id = fee.rider_id
    row.fee_cents = fee.fee_cents
    row.reason = fee.reason
    row.created_at = fee.created_at
    row.progress = fee.progress
    row.from_balance_cents = fee.from_balance_cents
    row.retained_cents = fee.retained_cents
    row.pending_cents = fee.pending_cents
    row.paid_later_cents = fee.paid_later_cents
    row.waived_cents = fee.waived_cents
    row.credited_back_cents = fee.credited_back_cents
    row.appeal_state = fee.appeal_state
    row.appeal_text = fee.appeal_text
    row.appealed_at = fee.appealed_at
    row.decided_at = fee.decided_at
    row.decided_by = fee.decided_by
    row.decision_note = fee.decision_note


def add_cancel_fee(session: Session, fee: CancelFee) -> None:
    row = CancelFeeRow(ride_id=fee.ride_id)
    _apply_fee(row, fee)
    session.add(row)
    session.flush()


def get_cancel_fee(session: Session, ride_id: str, *, for_update: bool = False) -> CancelFee:
    row = session.execute(_locking(select(CancelFeeRow).where(CancelFeeRow.ride_id == ride_id), for_update)).scalar_one_or_none()
    if row is None:
        raise LookupError(f"a corrida {ride_id} não tem taxa de cancelamento")
    return _fee_to_domain(row)


def save_cancel_fee(session: Session, fee: CancelFee) -> None:
    row = session.get(CancelFeeRow, fee.ride_id)
    if row is None:
        raise LookupError(f"a corrida {fee.ride_id} não tem taxa de cancelamento")
    _apply_fee(row, fee)
    session.flush()


def pending_cancel_fee(session: Session, passenger_id: str, *, for_update: bool = False) -> CancelFee | None:
    """A taxa com pendência mais antiga do passageiro, se houver."""
    stmt = (
        select(CancelFeeRow)
        .where(CancelFeeRow.passenger_id == passenger_id, CancelFeeRow.pending_cents > 0)
        .order_by(CancelFeeRow.created_at, CancelFeeRow.ride_id)
        .limit(1)
    )
    row = session.execute(_locking(stmt, for_update)).scalar_one_or_none()
    return None if row is None else _fee_to_domain(row)


def recent_cancel_fees(session: Session, passenger_id: str, since: float) -> list[CancelFee]:
    rows = session.execute(
        select(CancelFeeRow)
        .where(CancelFeeRow.passenger_id == passenger_id, CancelFeeRow.created_at >= since)
        .order_by(CancelFeeRow.created_at.desc(), CancelFeeRow.ride_id)
    ).scalars()
    return [_fee_to_domain(row) for row in rows]


def find_open_charge(session: Session, ride_id: str, purpose: str) -> PixCharge | None:
    """Cobrança do propósito pedido ainda não paga nem devolvida, para a mesma corrida."""
    row = session.execute(
        select(PixChargeRow)
        .where(
            PixChargeRow.ride_id == ride_id, PixChargeRow.purpose == purpose,
            PixChargeRow.paid.is_(False), PixChargeRow.refunded.is_(False),
        )
        .order_by(PixChargeRow.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return None if row is None else _charge_to_domain(row)


def find_open_topup_charge(session: Session, passenger_id: str) -> PixCharge | None:
    row = session.execute(
        select(PixChargeRow)
        .where(
            PixChargeRow.passenger_id == passenger_id, PixChargeRow.purpose == "topup",
            PixChargeRow.paid.is_(False), PixChargeRow.refunded.is_(False),
        )
        .order_by(PixChargeRow.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return None if row is None else _charge_to_domain(row)
