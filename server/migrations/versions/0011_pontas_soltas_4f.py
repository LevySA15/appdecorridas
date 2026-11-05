"""pontas soltas 4F: quem pediu o alerta de segurança, hora da recusa e reenvios do cadastro

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("safety_alerts", sa.Column("raised_by", sa.String(10), nullable=False, server_default="system"))
    op.create_check_constraint("alert_raised_by_valid", "safety_alerts", "raised_by IN ('system','passenger','rider')")
    # o SOS que já existe era sempre do passageiro (o do motoqueiro nasce nesta versão)
    op.execute("UPDATE safety_alerts SET raised_by = 'passenger' WHERE kind = 'sos'")
    op.add_column("rider_profiles", sa.Column("rejected_at", sa.Float(53), nullable=True))
    op.add_column("rider_profiles", sa.Column("previous_rejection", sa.String(200), nullable=True))
    op.add_column("rider_profiles", sa.Column("resubmissions", sa.Integer(), nullable=False, server_default=sa.text("0")))
    # quem já estava recusado começa a contar o prazo de guarda das fotos a partir de agora
    op.execute("UPDATE rider_profiles SET rejected_at = extract(epoch from now()) WHERE status = 'rejected'")


def downgrade() -> None:
    op.drop_column("rider_profiles", "resubmissions")
    op.drop_column("rider_profiles", "previous_rejection")
    op.drop_column("rider_profiles", "rejected_at")
    op.drop_constraint("alert_raised_by_valid", "safety_alerts")
    op.drop_column("safety_alerts", "raised_by")
