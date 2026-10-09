"""Tabelas do banco (SQLAlchemy 2.0).

A fonte da verdade do esquema são as migrações em `migrations/versions/`. Um teste confere que
migrações e modelos têm as mesmas tabelas e colunas.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))  # passenger | rider | admin
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiderProfileRow(Base):
    __tablename__ = "rider_profiles"
    __table_args__ = (
        CheckConstraint("cash_debt_cents >= 0", name="rider_debt_non_negative"),
        CheckConstraint("debt_reserved_cents >= 0", name="rider_reserved_non_negative"),
        CheckConstraint("debt_reserved_cents <= cash_debt_cents", name="rider_reserved_within_debt"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    cpf: Mapped[str] = mapped_column(String(14), unique=True)
    cnh_number: Mapped[str] = mapped_column(String(20), unique=True)
    plate: Mapped[str] = mapped_column(String(10), unique=True)
    moto_model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    completed_rides: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    entry_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cash_debt_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    debt_reserved_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassengerProfileRow(Base):
    __tablename__ = "passenger_profiles"
    __table_args__ = (CheckConstraint("unpaid_cents >= 0", name="passenger_unpaid_non_negative"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    unpaid_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class RideRow(Base):
    __tablename__ = "rides"
    __table_args__ = (CheckConstraint("price_cents > 0", name="ride_price_positive"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    rider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(8))  # pix | cash
    pin: Mapped[str] = mapped_column(String(4))
    state: Mapped[str] = mapped_column(String(16))
    helmet_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    pix_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    pix_charge_created_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    searching_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    queued_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    en_route_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    arrived_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    end_payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    non_payment_reported: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    current_charge_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PixChargeRow(Base):
    __tablename__ = "pix_charges"
    __table_args__ = (
        CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
    )

    charge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    rider_cents: Mapped[int] = mapped_column(Integer)
    company_cents: Mapped[int] = mapped_column(Integer)
    debt_paid_cents: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    debt_state: Mapped[str] = mapped_column(String(12), default="reserved", server_default="reserved")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerRow(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index(
            "ledger_once_per_kind", "ref", "kind", "account",
            unique=True, postgresql_where=text("kind <> 'correction'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ref: Mapped[str] = mapped_column(String(80), index=True)
    account: Mapped[str] = mapped_column(String(80))
    amount_cents: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedEventRow(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    processed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppConfigRow(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
