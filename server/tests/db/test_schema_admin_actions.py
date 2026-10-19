import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import AdminActionRow
from app.db import repositories as repo


def test_acao_do_administrador_e_gravada_e_recusa_administrador_que_nao_existe(session):
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    session.add(AdminActionRow(admin_id="adm-1", action="rider.approve", target_type="rider", target_id="r1", detail="", created_at=1.0))
    session.flush()
    assert session.query(AdminActionRow).one().action == "rider.approve"
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(AdminActionRow(admin_id="ninguem", action="x", target_type="rider", target_id="r1", detail="", created_at=1.0))
            session.flush()
