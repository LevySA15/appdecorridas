"""Leitura e gravação dos objetos do domínio no PostgreSQL.

Nenhuma função faz commit: quem chama controla a transação. Quando uma operação precisa travar
várias linhas, a ordem é sempre corrida, motoqueiro, cobrança (evita impasse entre transações).
"""
from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    PassengerProfileRow,
    PixChargeRow,
    ProcessedEventRow,
    RideRow,
    RiderProfileRow,
    UserRow,
)
from app.domain.fees import RiderAccount
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
    return PassengerAccount(passenger_id=row.user_id, unpaid_cents=row.unpaid_cents)


def save_passenger_account(session: Session, acc: PassengerAccount) -> None:
    row = session.get(PassengerProfileRow, acc.passenger_id)
    if row is None:
        raise LookupError(f"passageiro {acc.passenger_id} não encontrado")
    row.unpaid_cents = acc.unpaid_cents
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
        ride_id=row.ride_id,
        rider_id=row.rider_id,
        amount_cents=row.amount_cents,
        split=Split(
            rider_cents=row.rider_cents,
            company_cents=row.company_cents,
            debt_paid_cents=row.debt_paid_cents,
        ),
        paid=row.paid,
        refunded=row.refunded,
        debt_state=DebtState(row.debt_state),
    )


def _apply_charge(row: PixChargeRow, charge: PixCharge) -> None:
    row.ride_id = charge.ride_id
    row.rider_id = charge.rider_id
    row.amount_cents = charge.amount_cents
    row.rider_cents = charge.split.rider_cents
    row.company_cents = charge.split.company_cents
    row.debt_paid_cents = charge.split.debt_paid_cents
    row.paid = charge.paid
    row.refunded = charge.refunded
    row.debt_state = charge.debt_state.value


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
