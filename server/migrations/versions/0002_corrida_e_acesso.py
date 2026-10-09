"""corrida e acesso: login, sessões, cotações, ofertas, eventos, avaliações e campos novos

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _false() -> sa.TextClause:
    return sa.text("false")


def upgrade() -> None:
    # --- colunas novas ---------------------------------------------------------
    for name, type_ in (
        ("pickup_lat", sa.Float(53)), ("pickup_lng", sa.Float(53)),
        ("dest_lat", sa.Float(53)), ("dest_lng", sa.Float(53)),
        ("pickup_text", sa.String(200)), ("dest_text", sa.String(200)),
        ("distance_m", sa.Integer()), ("price_factor", sa.Float(53)), ("price_reason", sa.String(80)),
        ("fee_cents", sa.Integer()), ("completed_at", sa.Float(53)),
    ):
        op.add_column("rides", sa.Column(name, type_, nullable=True))

    op.add_column("rider_profiles", sa.Column("online", sa.Boolean(), nullable=False, server_default=_false()))
    for name, type_ in (
        ("rejected_reason", sa.String(200)), ("selfie_key", sa.String(200)),
        ("cnh_photo_key", sa.String(200)), ("crlv_key", sa.String(200)),
        ("cnh_expires_on", sa.Date()), ("crlv_expires_on", sa.Date()),
    ):
        op.add_column("rider_profiles", sa.Column(name, type_, nullable=True))
    op.add_column("rider_profiles", sa.Column("rating_sum", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("rider_profiles", sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    op.alter_column("pix_charges", "ride_id", existing_type=sa.String(40), nullable=True)
    op.add_column("pix_charges", sa.Column("purpose", sa.String(8), nullable=False, server_default="ride"))
    op.create_check_constraint("charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry')")
    op.create_check_constraint("charge_ride_required", "pix_charges", "purpose = 'entry' OR ride_id IS NOT NULL")

    # --- tabelas novas ---------------------------------------------------------
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=_false()),
    )
    op.create_index("ix_otp_codes_phone", "otp_codes", ["phone"])

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=_false()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pickup_lat", sa.Float(53), nullable=False),
        sa.Column("pickup_lng", sa.Float(53), nullable=False),
        sa.Column("dest_lat", sa.Float(53), nullable=False),
        sa.Column("dest_lng", sa.Float(53), nullable=False),
        sa.Column("pickup_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("dest_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("factor", sa.Float(53), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=_false()),
    )

    op.create_table(
        "ride_offers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("will_queue", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("status IN ('pending','accepted','declined','expired')", name="offer_status_valid"),
    )
    op.create_index(
        "offer_one_pending_per_ride", "ride_offers", ["ride_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "offer_one_pending_per_rider", "ride_offers", ["rider_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "ride_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.Float(53), nullable=False),
    )
    op.create_index("ix_ride_events_ride_id", "ride_events", ["ride_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("from_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name="rating_range"),
        sa.UniqueConstraint("ride_id", "from_user", name="rating_once"),
    )


def downgrade() -> None:
    op.drop_table("ratings")
    op.drop_table("ride_events")
    op.drop_table("ride_offers")
    op.drop_table("quotes")
    op.drop_table("sessions")
    op.drop_table("otp_codes")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.drop_column("pix_charges", "purpose")
    op.alter_column("pix_charges", "ride_id", existing_type=sa.String(40), nullable=False)
    for name in (
        "rating_count", "rating_sum", "crlv_expires_on", "cnh_expires_on", "crlv_key",
        "cnh_photo_key", "selfie_key", "rejected_reason", "online",
    ):
        op.drop_column("rider_profiles", name)
    for name in (
        "completed_at", "fee_cents", "price_reason", "price_factor", "distance_m", "dest_text",
        "pickup_text", "dest_lng", "dest_lat", "pickup_lng", "pickup_lat",
    ):
        op.drop_column("rides", name)
