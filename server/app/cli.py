"""Comandos de manutenção. Uso (a partir de `server/`):

    .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy"
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import UserRow
from app.domain.ids import new_id
from app.services.auth import normalize_phone


def create_admin(session: Session, raw_phone: str, name: str) -> str:
    """Cria o administrador (ou devolve o que já existe com este número). Devolve o id."""
    phone = normalize_phone(raw_phone)
    existing = session.execute(select(UserRow).where(UserRow.phone == phone)).scalar_one_or_none()
    if existing is not None:
        if existing.role != "admin":
            raise ValueError(f"Este número já é de {'passageiro' if existing.role == 'passenger' else 'motoqueiro'}.")
        return existing.id
    user_id = new_id("adm")
    repo.add_user(session, user_id=user_id, phone=phone, name=name.strip(), role="admin")
    return user_id


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="cria o acesso de administrador do painel")
    admin.add_argument("--phone", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    if session_factory is None:
        from app.db.session import make_engine, make_session_factory
        from app.settings import load_settings

        session_factory = make_session_factory(make_engine(load_settings()))
    try:
        with session_factory() as session:
            user_id = create_admin(session, args.phone, args.name)
            session.commit()
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(f"Administrador pronto: {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
