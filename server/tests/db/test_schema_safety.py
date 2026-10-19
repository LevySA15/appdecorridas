import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import RideRow, SafetyAlertRow
from tests.helpers_db import add_passenger, add_rider


def _corrida(session):
    add_passenger(session)
    add_rider(session)
    session.add(
        RideRow(id="ride-1", passenger_id="p1", rider_id="r1", price_cents=700, payment_method="cash", pin="1234", state="in_progress")
    )
    session.flush()


def test_alerta_de_seguranca_guarda_o_que_aconteceu_e_a_resposta(session):
    _corrida(session)
    session.add(SafetyAlertRow(ride_id="ride-1", kind="stopped", lat=-12.96, lng=-39.26, created_at=100.0))
    session.flush()
    alerta = session.query(SafetyAlertRow).one()
    assert (alerta.status, alerta.suspected_mock, alerta.answered_at, alerta.resolved_at) == ("open", False, None, None)


@pytest.mark.parametrize("campo, valor", [("kind", "invasao"), ("status", "perdido")])
def test_tipo_e_situacao_do_alerta_so_aceitam_os_valores_conhecidos(session, campo, valor):
    _corrida(session)
    dados = dict(ride_id="ride-1", kind="stopped", status="open", created_at=1.0) | {campo: valor}
    with pytest.raises(IntegrityError):
        session.add(SafetyAlertRow(**dados))
        session.flush()


def test_alerta_de_sem_sinal_e_aceito_pelo_banco(session):
    _corrida(session)
    session.add(SafetyAlertRow(ride_id="ride-1", kind="no_signal", created_at=1.0))
    session.flush()
    assert session.query(SafetyAlertRow).one().kind == "no_signal"
