"""robustez 4H: índices das listas do painel e da varredura de "sem sinal"

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_rides_created_at", "rides", ["created_at"])
    op.create_index("ix_ride_events_kind_ride", "ride_events", ["kind", "ride_id"])


def downgrade() -> None:
    op.drop_index("ix_ride_events_kind_ride", table_name="ride_events")
    op.drop_index("ix_rides_created_at", table_name="rides")
