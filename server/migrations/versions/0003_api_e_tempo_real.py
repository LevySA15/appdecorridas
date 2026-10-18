"""api e tempo real: código do Pix, rota da corrida, contato de emergência, chave e índices

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_ABERTA = "state NOT IN ('completed','cancelled','no_rider')"


def upgrade() -> None:
    op.add_column("pix_charges", sa.Column("br_code", sa.Text(), nullable=False, server_default=""))
    op.add_column("quotes", sa.Column("route", postgresql.JSONB(), nullable=True))
    op.add_column("rides", sa.Column("route", postgresql.JSONB(), nullable=True))
    op.add_column("ride_offers", sa.Column("eta_seconds", sa.Integer(), nullable=True))
    op.add_column("passenger_profiles", sa.Column("emergency_name", sa.String(120), nullable=True))
    op.add_column("passenger_profiles", sa.Column("emergency_phone", sa.String(20), nullable=True))

    op.create_foreign_key("rides_current_charge_fk", "rides", "pix_charges", ["current_charge_id"], ["charge_id"])
    op.create_index("ix_rides_state", "rides", ["state"])
    op.create_index("ix_rides_passenger_state", "rides", ["passenger_id", "state"])
    op.create_index("ix_rides_rider_state", "rides", ["rider_id", "state"])
    op.create_index("ix_ride_offers_ride_id", "ride_offers", ["ride_id"])
    op.create_index(
        "ride_one_open_per_passenger", "rides", ["passenger_id"], unique=True, postgresql_where=sa.text(_ABERTA)
    )


def downgrade() -> None:
    op.drop_index("ride_one_open_per_passenger", table_name="rides")
    op.drop_index("ix_ride_offers_ride_id", table_name="ride_offers")
    op.drop_index("ix_rides_rider_state", table_name="rides")
    op.drop_index("ix_rides_passenger_state", table_name="rides")
    op.drop_index("ix_rides_state", table_name="rides")
    op.drop_constraint("rides_current_charge_fk", "rides", type_="foreignkey")
    op.drop_column("passenger_profiles", "emergency_phone")
    op.drop_column("passenger_profiles", "emergency_name")
    op.drop_column("ride_offers", "eta_seconds")
    op.drop_column("rides", "route")
    op.drop_column("quotes", "route")
    op.drop_column("pix_charges", "br_code")
