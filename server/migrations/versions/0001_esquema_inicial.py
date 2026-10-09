"""esquema inicial: usuários, perfis, corridas, cobranças Pix, livro-caixa, eventos e configuração

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_NOW = sa.func.now()


def _false() -> sa.TextClause:
    return sa.text("false")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "rider_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("cpf", sa.String(14), nullable=False, unique=True),
        sa.Column("cnh_number", sa.String(20), nullable=False, unique=True),
        sa.Column("plate", sa.String(10), nullable=False, unique=True),
        sa.Column("moto_model", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("completed_rides", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("entry_paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("cash_debt_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("debt_reserved_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cash_debt_cents >= 0", name="rider_debt_non_negative"),
        sa.CheckConstraint("debt_reserved_cents >= 0", name="rider_reserved_non_negative"),
        sa.CheckConstraint("debt_reserved_cents <= cash_debt_cents", name="rider_reserved_within_debt"),
    )
    op.create_table(
        "passenger_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("unpaid_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("unpaid_cents >= 0", name="passenger_unpaid_non_negative"),
    )
    op.create_table(
        "rides",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(8), nullable=False),
        sa.Column("pin", sa.String(4), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("helmet_confirmed", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("pix_paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("pix_charge_created_at", sa.Float(53), nullable=True),
        sa.Column("searching_since", sa.Float(53), nullable=True),
        sa.Column("queued_since", sa.Float(53), nullable=True),
        sa.Column("en_route_since", sa.Float(53), nullable=True),
        sa.Column("arrived_at", sa.Float(53), nullable=True),
        sa.Column("end_payment_confirmed", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("non_payment_reported", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("current_charge_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("price_cents > 0", name="ride_price_positive"),
    )
    op.create_table(
        "pix_charges",
        sa.Column("charge_id", sa.String(40), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("rider_cents", sa.Integer(), nullable=False),
        sa.Column("company_cents", sa.Integer(), nullable=False),
        sa.Column("debt_paid_cents", sa.Integer(), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("refunded", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("debt_state", sa.String(12), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ref", sa.String(80), nullable=False),
        sa.Column("account", sa.String(80), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_ledger_entries_ref", "ledger_entries", ["ref"])
    op.create_index(
        "ledger_once_per_kind",
        "ledger_entries",
        ["ref", "kind", "account"],
        unique=True,
        postgresql_where=sa.text("kind <> 'correction'"),
    )
    op.execute(
        """
        CREATE FUNCTION ledger_no_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'o livro-caixa so aceita novos lancamentos';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER ledger_append_only BEFORE UPDATE OR DELETE ON ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION ledger_no_change()"
    )
    op.execute(
        "CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON ledger_entries "
        "FOR EACH STATEMENT EXECUTE FUNCTION ledger_no_change()"
    )
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(120), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_table("processed_events")
    op.execute("DROP TRIGGER ledger_no_truncate ON ledger_entries")
    op.execute("DROP TRIGGER ledger_append_only ON ledger_entries")
    op.execute("DROP FUNCTION ledger_no_change()")
    op.drop_table("ledger_entries")
    op.drop_table("pix_charges")
    op.drop_table("rides")
    op.drop_table("passenger_profiles")
    op.drop_table("rider_profiles")
    op.drop_table("users")
