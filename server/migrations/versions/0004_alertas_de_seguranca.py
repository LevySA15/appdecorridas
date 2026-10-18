"""alertas de segurança da corrida (parada longa, saída da rota, SOS)

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("suspected_mock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lat", sa.Float(53), nullable=True),
        sa.Column("lng", sa.Float(53), nullable=True),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("answered_at", sa.Float(53), nullable=True),
        sa.Column("resolved_at", sa.Float(53), nullable=True),
        sa.Column("resolved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.CheckConstraint("kind IN ('stopped','off_route','sos')", name="alert_kind_valid"),
        sa.CheckConstraint("status IN ('open','ok','sos','resolved')", name="alert_status_valid"),
    )
    op.create_index("ix_safety_alerts_status", "safety_alerts", ["status"])
    op.create_index("ix_safety_alerts_ride_id", "safety_alerts", ["ride_id"])


def downgrade() -> None:
    op.drop_table("safety_alerts")
