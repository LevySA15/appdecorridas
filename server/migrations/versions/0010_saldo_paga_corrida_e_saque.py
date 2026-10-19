"""saldo que paga corrida e pode ser sacado: marca na corrida, origem da cobrança e tabela de saques

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rides", sa.Column("pay_with_balance", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("pix_charges", sa.Column("source", sa.String(8), nullable=False, server_default="pix"))
    op.create_check_constraint("charge_source_valid", "pix_charges", "source IN ('pix','balance')")
    op.create_table(
        "withdrawals",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("key_kind", sa.String(10), nullable=False),
        sa.Column("key_masked", sa.String(40), nullable=False),
        sa.Column("provider_ref", sa.String(60), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="withdrawal_amount_positive"),
    )
    op.create_index("ix_withdrawals_passenger_id", "withdrawals", ["passenger_id"])
    op.create_index("ix_withdrawals_created_at", "withdrawals", ["created_at"])


def downgrade() -> None:
    op.drop_table("withdrawals")
    op.drop_constraint("charge_source_valid", "pix_charges")
    op.drop_column("pix_charges", "source")
    op.drop_column("rides", "pay_with_balance")
