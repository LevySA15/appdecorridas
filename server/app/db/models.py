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
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    online: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    rejected_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    selfie_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cnh_photo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    crlv_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cnh_expires_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    crlv_expires_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    rating_sum: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class PassengerProfileRow(Base):
    __tablename__ = "passenger_profiles"
    __table_args__ = (
        CheckConstraint("unpaid_cents >= 0", name="passenger_unpaid_non_negative"),
        CheckConstraint("balance_cents >= 0", name="passenger_balance_non_negative"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    unpaid_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    balance_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    emergency_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)


class RideRow(Base):
    __tablename__ = "rides"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="ride_price_positive"),
        Index("ix_rides_state", "state"),
        Index("ix_rides_passenger_state", "passenger_id", "state"),
        Index("ix_rides_rider_state", "rider_id", "state"),
        Index(
            "ride_one_open_per_passenger", "passenger_id", unique=True,
            postgresql_where=text("state NOT IN ('completed','cancelled','no_rider')"),
        ),
    )

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
    current_charge_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("pix_charges.charge_id", use_alter=True, name="rides_current_charge_fk"), nullable=True
    )
    pickup_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    pickup_lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    dest_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    dest_lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    pickup_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dest_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_factor: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    price_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [[lat, lng], ...] do preço mostrado
    fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approach_start_m: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    pay_with_balance: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    completed_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PixChargeRow(Base):
    __tablename__ = "pix_charges"
    __table_args__ = (
        CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
        CheckConstraint("purpose IN ('ride','end','entry','fee','topup','debt')", name="charge_purpose_valid"),
        CheckConstraint("source IN ('pix','balance')", name="charge_source_valid"),
        CheckConstraint("purpose IN ('entry','topup','debt') OR ride_id IS NOT NULL", name="charge_ride_required"),
        CheckConstraint(
            "(purpose = 'topup' AND passenger_id IS NOT NULL AND rider_id IS NULL)"
            " OR (purpose <> 'topup' AND rider_id IS NOT NULL)",
            name="charge_owner",
        ),
    )

    charge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ride_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("rides.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(8), default="ride", server_default="ride")
    source: Mapped[str] = mapped_column(String(8), default="pix", server_default="pix")
    rider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    passenger_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    rider_cents: Mapped[int] = mapped_column(Integer)
    company_cents: Mapped[int] = mapped_column(Integer)
    debt_paid_cents: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    debt_state: Mapped[str] = mapped_column(String(12), default="reserved", server_default="reserved")
    br_code: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WithdrawalRow(Base):
    __tablename__ = "withdrawals"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="withdrawal_amount_positive"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    key_kind: Mapped[str] = mapped_column(String(10))
    key_masked: Mapped[str] = mapped_column(String(40))         # só o final: a chave inteira nunca é guardada
    provider_ref: Mapped[str] = mapped_column(String(60))       # a referência enviada ao provedor (o id do saque)
    created_at: Mapped[float] = mapped_column(Float(53), index=True)


class CancelFeeRow(Base):
    __tablename__ = "cancel_fees"
    __table_args__ = (
        CheckConstraint("fee_cents > 0", name="fee_positive"),
        CheckConstraint(
            "from_balance_cents >= 0 AND retained_cents >= 0 AND pending_cents >= 0 AND paid_later_cents >= 0"
            " AND waived_cents >= 0 AND credited_back_cents >= 0",
            name="fee_parts_non_negative",
        ),
        CheckConstraint(
            "from_balance_cents + retained_cents + pending_cents + paid_later_cents + waived_cents = fee_cents",
            name="fee_parts_close",
        ),
        CheckConstraint("appeal_state IN ('none','open','accepted','rejected')", name="appeal_state_valid"),
        Index("ix_cancel_fees_passenger", "passenger_id"),
        Index("ix_cancel_fees_appeal", "appeal_state"),
    )

    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    fee_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(16))             # passenger | arrival_timeout
    traveled_m: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    from_balance_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    retained_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    pending_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    paid_later_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    waived_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    credited_back_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    appeal_state: Mapped[str] = mapped_column(String(10), default="none", server_default="none")
    appeal_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    appealed_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    decided_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[float] = mapped_column(Float(53))


class AdminActionRow(Base):
    """O que cada administrador fez no painel (só ações de escrita)."""

    __tablename__ = "admin_actions"
    __table_args__ = (Index("ix_admin_actions_created", "created_at"), Index("ix_admin_actions_admin", "admin_id"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[float] = mapped_column(Float(53))


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


class OtpCodeRow(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class SessionRow(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    device: Mapped[str] = mapped_column(String(80), default="", server_default="")
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class QuoteRow(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    pickup_lat: Mapped[float] = mapped_column(Float(53))
    pickup_lng: Mapped[float] = mapped_column(Float(53))
    dest_lat: Mapped[float] = mapped_column(Float(53))
    dest_lng: Mapped[float] = mapped_column(Float(53))
    pickup_text: Mapped[str] = mapped_column(String(200), default="", server_default="")
    dest_text: Mapped[str] = mapped_column(String(200), default="", server_default="")
    distance_m: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    factor: Mapped[float] = mapped_column(Float(53))
    reason: Mapped[str] = mapped_column(String(80))
    route: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class RideOfferRow(Base):
    __tablename__ = "ride_offers"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired')", name="offer_status_valid"),
        Index("offer_one_pending_per_ride", "ride_id", unique=True, postgresql_where=text("status = 'pending'")),
        Index("offer_one_pending_per_rider", "rider_id", unique=True, postgresql_where=text("status = 'pending'")),
        Index("ix_ride_offers_ride_id", "ride_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    will_queue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))


class RideEventRow(Base):
    __tablename__ = "ride_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[float] = mapped_column(Float(53))


class SafetyAlertRow(Base):
    __tablename__ = "safety_alerts"
    __table_args__ = (
        CheckConstraint("kind IN ('stopped','off_route','sos','no_signal')", name="alert_kind_valid"),
        CheckConstraint("status IN ('open','ok','sos','resolved')", name="alert_status_valid"),
        Index("ix_safety_alerts_status", "status"),
        Index("ix_safety_alerts_ride_id", "ride_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    suspected_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    created_at: Mapped[float] = mapped_column(Float(53))
    answered_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    resolved_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class RatingRow(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint("stars BETWEEN 1 AND 5", name="rating_range"),
        UniqueConstraint("ride_id", "from_user", name="rating_once"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    from_user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    to_user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    stars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float(53))
