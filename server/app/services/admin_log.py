"""Registro das ações de escrita do administrador no painel (quem fez o quê, em quem, quando)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdminActionRow, UserRow


@dataclass(frozen=True)
class AdminActionItem:
    id: int
    admin_id: str
    admin_name: str
    action: str
    target_type: str
    target_id: str
    detail: str
    at: float


def log_admin_action(
    session: Session, admin_id: str, action: str, target_type: str, target_id: str, detail: str, now: float
) -> None:
    """Grava na mesma transação da ação: se a ação falhar, o registro some junto."""
    session.add(
        AdminActionRow(
            admin_id=admin_id, action=action, target_type=target_type, target_id=target_id,
            detail=(detail or "")[:300], created_at=now,
        )
    )
    session.flush()


def list_admin_actions(session: Session, limit: int, offset: int) -> list[AdminActionItem]:
    rows = session.execute(
        select(AdminActionRow, UserRow.name)
        .join(UserRow, UserRow.id == AdminActionRow.admin_id)
        .order_by(AdminActionRow.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        AdminActionItem(a.id, a.admin_id, name, a.action, a.target_type, a.target_id, a.detail, a.created_at)
        for a, name in rows
    ]
