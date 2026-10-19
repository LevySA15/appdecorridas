"""alerta de muito tempo sem sinal da moto no meio da corrida

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("alert_kind_valid", "safety_alerts")
    op.create_check_constraint(
        "alert_kind_valid", "safety_alerts", "kind IN ('stopped','off_route','sos','no_signal')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM safety_alerts WHERE kind = 'no_signal'")
    op.drop_constraint("alert_kind_valid", "safety_alerts")
    op.create_check_constraint("alert_kind_valid", "safety_alerts", "kind IN ('stopped','off_route','sos')")
