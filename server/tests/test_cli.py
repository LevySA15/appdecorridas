import pytest
from sqlalchemy import select

from app.cli import create_admin, main
from app.db import repositories as repo
from app.db.models import UserRow


def test_cria_o_administrador_com_o_numero_normalizado(session):
    user_id = create_admin(session, "75 99999-0000", "Levy")
    user = session.get(UserRow, user_id)
    assert (user.phone, user.name, user.role, user.is_blocked) == ("+5575999990000", "Levy", "admin", False)


def test_repetir_o_comando_nao_cria_outro(session):
    primeiro = create_admin(session, "75 99999-0000", "Levy")
    assert create_admin(session, "(75) 99999-0000", "Levy") == primeiro
    assert len(session.execute(select(UserRow)).all()) == 1


def test_numero_de_passageiro_nao_vira_administrador(session):
    repo.add_user(session, user_id="p1", phone="+5575999990000", name="Ana", role="passenger")
    with pytest.raises(ValueError, match="passageiro"):
        create_admin(session, "75 99999-0000", "Levy")


def test_numero_invalido_da_erro_claro(session):
    with pytest.raises(ValueError, match="celular"):
        create_admin(session, "123", "Levy")


def test_linha_de_comando_cria_e_avisa(session, capsys):
    codigo = main(["create-admin", "--phone", "75 99999-0000", "--name", "Levy"], session_factory=lambda: session)
    assert codigo == 0 and "Administrador pronto" in capsys.readouterr().out
    codigo = main(["create-admin", "--phone", "123", "--name", "Levy"], session_factory=lambda: session)
    assert codigo == 1 and "celular" in capsys.readouterr().err
