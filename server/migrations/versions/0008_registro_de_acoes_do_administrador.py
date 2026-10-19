"""registro das ações do administrador no painel

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("admin_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(60), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(53), nullable=False),
    )
    op.create_index("ix_admin_actions_created", "admin_actions", ["created_at"])
    op.create_index("ix_admin_actions_admin", "admin_actions", ["admin_id"])


def downgrade() -> None:
    op.drop_table("admin_actions")
