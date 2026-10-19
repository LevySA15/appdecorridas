"""cobrança Pix para o motoqueiro pagar a dívida da taxa

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.create_check_constraint(
        "charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry','fee','topup','debt')"
    )
    op.create_check_constraint(
        "charge_ride_required", "pix_charges", "purpose IN ('entry','topup','debt') OR ride_id IS NOT NULL"
    )


def downgrade() -> None:
    # Cobranças de dívida não existem no esquema anterior: somem junto (o livro-caixa não é tocado).
    op.execute("DELETE FROM pix_charges WHERE purpose = 'debt'")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.create_check_constraint(
        "charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry','fee','topup')"
    )
    op.create_check_constraint(
        "charge_ride_required", "pix_charges", "purpose IN ('entry','topup') OR ride_id IS NOT NULL"
    )
