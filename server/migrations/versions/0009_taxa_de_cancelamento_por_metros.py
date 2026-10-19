"""taxa de cancelamento por metros andados: a coluna progress (fração) vira traveled_m (metros)

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cancel_fees", "progress", new_column_name="traveled_m")
    # as frações antigas (0 a 1) não são metros: não dá para converter, então ficam sem valor
    op.execute("UPDATE cancel_fees SET traveled_m = NULL")


def downgrade() -> None:
    op.execute("UPDATE cancel_fees SET traveled_m = NULL")
    op.alter_column("cancel_fees", "traveled_m", new_column_name="progress")
