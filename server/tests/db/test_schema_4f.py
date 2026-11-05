import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import RideRow, RiderProfileRow, SafetyAlertRow
from tests.helpers_db import add_passenger, add_rider


def _corrida(session):
    add_passenger(session)
    add_rider(session)
    session.add(
        RideRow(id="ride-1", passenger_id="p1", rider_id="r1", price_cents=700, payment_method="cash", pin="1234", state="in_progress")
    )
    session.flush()


def test_alerta_sem_dono_e_do_sistema(session):
    _corrida(session)
    session.add(SafetyAlertRow(ride_id="ride-1", kind="stopped", created_at=1.0))
    session.flush()
    assert session.query(SafetyAlertRow).one().raised_by == "system"


@pytest.mark.parametrize("quem", ["system", "passenger", "rider"])
def test_alerta_aceita_quem_pediu(session, quem):
    _corrida(session)
    session.add(SafetyAlertRow(ride_id="ride-1", kind="sos", status="sos", raised_by=quem, created_at=1.0))
    session.flush()
    assert session.query(SafetyAlertRow).one().raised_by == quem


def test_alerta_recusa_quem_pediu_desconhecido(session):
    _corrida(session)
    with pytest.raises(IntegrityError):
        session.add(SafetyAlertRow(ride_id="ride-1", kind="sos", status="sos", raised_by="xpto", created_at=1.0))
        session.flush()


def test_cadastro_novo_nao_tem_recusa_nem_reenvio(session):
    add_rider(session)
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.rejected_at, perfil.previous_rejection, perfil.resubmissions) == (None, None, 0)


def test_cadastro_guarda_a_recusa_e_os_reenvios(session):
    add_rider(session)
    perfil = session.get(RiderProfileRow, "r1")
    perfil.rejected_at, perfil.previous_rejection, perfil.resubmissions = 500.0, "Foto ilegível", 2
    session.flush()
    session.expire(perfil)
    assert (perfil.rejected_at, perfil.previous_rejection, perfil.resubmissions) == (500.0, "Foto ilegível", 2)
