"""saldo do passageiro, taxa de cancelamento tardio, cobranças de taxa e de recarga

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("passenger_profiles", sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("passenger_balance_non_negative", "passenger_profiles", "balance_cents >= 0")
    op.add_column("rides", sa.Column("approach_start_m", sa.Float(53), nullable=True))

    op.add_column("pix_charges", sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
    op.alter_column("pix_charges", "rider_id", existing_type=sa.String(36), nullable=True)
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.create_check_constraint(
        "charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry','fee','topup')"
    )
    op.create_check_constraint(
        "charge_ride_required", "pix_charges", "purpose IN ('entry','topup') OR ride_id IS NOT NULL"
    )
    op.create_check_constraint(
        "charge_owner",
        "pix_charges",
        "(purpose = 'topup' AND passenger_id IS NOT NULL AND rider_id IS NULL)"
        " OR (purpose <> 'topup' AND rider_id IS NOT NULL)",
    )

    op.create_table(
        "cancel_fees",
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fee_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(53), nullable=True),
        sa.Column("from_balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retained_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_later_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waived_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credited_back_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("appeal_state", sa.String(10), nullable=False, server_default="none"),
        sa.Column("appeal_text", sa.String(500), nullable=True),
        sa.Column("appealed_at", sa.Float(53), nullable=True),
        sa.Column("decided_at", sa.Float(53), nullable=True),
        sa.Column("decided_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("fee_cents > 0", name="fee_positive"),
        sa.CheckConstraint(
            "from_balance_cents >= 0 AND retained_cents >= 0 AND pending_cents >= 0 AND paid_later_cents >= 0"
            " AND waived_cents >= 0 AND credited_back_cents >= 0",
            name="fee_parts_non_negative",
        ),
        sa.CheckConstraint(
            "from_balance_cents + retained_cents + pending_cents + paid_later_cents + waived_cents = fee_cents",
            name="fee_parts_close",
        ),
        sa.CheckConstraint("appeal_state IN ('none','open','accepted','rejected')", name="appeal_state_valid"),
    )
    op.create_index("ix_cancel_fees_passenger", "cancel_fees", ["passenger_id"])
    op.create_index("ix_cancel_fees_appeal", "cancel_fees", ["appeal_state"])


def downgrade() -> None:
    op.drop_table("cancel_fees")
    # Cobranças de taxa e de recarga não existem no esquema antigo: somem junto (o livro-caixa não é tocado).
    op.execute("DELETE FROM pix_charges WHERE purpose IN ('fee','topup')")
    op.drop_constraint("charge_owner", "pix_charges")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.create_check_constraint("charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry')")
    op.create_check_constraint("charge_ride_required", "pix_charges", "purpose = 'entry' OR ride_id IS NOT NULL")
    op.alter_column("pix_charges", "rider_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("pix_charges", "passenger_id")
    op.drop_column("rides", "approach_start_m")
    op.drop_constraint("passenger_balance_non_negative", "passenger_profiles")
    op.drop_column("passenger_profiles", "balance_cents")
