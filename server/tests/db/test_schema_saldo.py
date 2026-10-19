import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import CancelFeeRow, PassengerProfileRow, PixChargeRow
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def _corrida(session) -> None:
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)


def _taxa(**extra) -> CancelFeeRow:
    dados = dict(
        ride_id="ride-1", passenger_id="p1", rider_id="r1", fee_cents=400, reason="passenger", created_at=1.0,
        from_balance_cents=100, retained_cents=0, pending_cents=300, paid_later_cents=0, waived_cents=0,
        credited_back_cents=0,
    ) | extra
    return CancelFeeRow(**dados)


def _cobranca(**extra) -> PixChargeRow:
    dados = dict(
        charge_id="ch-1", ride_id="ride-1", purpose="fee", rider_id="r1", amount_cents=300, rider_cents=300,
        company_cents=0, debt_paid_cents=0,
    ) | extra
    return PixChargeRow(**dados)


def _recusa(session, *linhas) -> None:
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add_all(linhas)
            session.flush()


def test_saldo_negativo_e_recusado_pelo_banco(session):
    add_passenger(session)
    session.get(PassengerProfileRow, "p1").balance_cents = -1
    with pytest.raises(IntegrityError):
        session.flush()


def test_saldo_comeca_em_zero(session):
    add_passenger(session)
    assert session.get(PassengerProfileRow, "p1").balance_cents == 0


def test_taxa_com_partes_que_fecham_e_aceita(session):
    _corrida(session)
    session.add(_taxa())
    session.flush()
    assert session.get(CancelFeeRow, "ride-1").appeal_state == "none"


def test_taxa_com_partes_que_nao_fecham_e_recusada(session):
    _corrida(session)
    _recusa(session, _taxa(pending_cents=250))


@pytest.mark.parametrize("campo", ["from_balance_cents", "retained_cents", "pending_cents", "waived_cents"])
def test_parte_negativa_da_taxa_e_recusada(session, campo):
    _corrida(session)
    _recusa(session, _taxa(**{campo: -50, "pending_cents": 450 - 0 if campo != "pending_cents" else -50}))


def test_taxa_zero_ou_negativa_e_recusada(session):
    _corrida(session)
    _recusa(session, _taxa(fee_cents=0, from_balance_cents=0, pending_cents=0))


def test_taxa_de_cancelamento_so_aceita_situacao_de_recurso_conhecida(session):
    _corrida(session)
    _recusa(session, _taxa(appeal_state="perdido"))


def test_so_uma_taxa_por_corrida(session):
    _corrida(session)
    session.add(_taxa())
    session.flush()
    _recusa(session, _taxa())


def test_cobranca_de_taxa_exige_corrida(session):
    _corrida(session)
    _recusa(session, _cobranca(ride_id=None))


def test_cobranca_de_taxa_com_corrida_e_aceita(session):
    _corrida(session)
    session.add(_cobranca())
    session.flush()


def test_recarga_exige_passageiro_e_nao_aceita_motoqueiro(session):
    _corrida(session)
    recarga = dict(
        charge_id="ch-2", ride_id=None, purpose="topup", rider_id=None, passenger_id="p1", amount_cents=2000,
        rider_cents=0, company_cents=2000,
    )
    session.add(_cobranca(**recarga))
    session.flush()                                                     # a forma certa passa
    _recusa(session, _cobranca(**(recarga | {"charge_id": "ch-3", "rider_id": "r1"})))
    _recusa(session, _cobranca(**(recarga | {"charge_id": "ch-4", "passenger_id": None})))


def test_cobranca_que_nao_e_recarga_exige_motoqueiro(session):
    _corrida(session)
    _recusa(session, _cobranca(rider_id=None))


def test_proposito_desconhecido_de_cobranca_e_recusado(session):
    _corrida(session)
    _recusa(session, _cobranca(purpose="doacao"))


def test_cobranca_de_divida_do_motoqueiro_nao_precisa_de_corrida_mas_precisa_do_motoqueiro(session):
    _corrida(session)
    divida = dict(charge_id="ch-d1", ride_id=None, purpose="debt", amount_cents=100, rider_cents=0, company_cents=100)
    session.add(_cobranca(**divida))
    session.flush()
    _recusa(session, _cobranca(**(divida | {"charge_id": "ch-d2", "rider_id": None})))
