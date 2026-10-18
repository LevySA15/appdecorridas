import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import Base, PassengerProfileRow, PixChargeRow, QuoteRow, RideOfferRow, RideRow
from tests.helpers_db import add_passenger, add_rider


def _ride(ride_id: str, passenger_id: str = "p1", state: str = "searching", **extra) -> RideRow:
    return RideRow(
        id=ride_id, passenger_id=passenger_id, price_cents=700, payment_method="pix", pin="4821", state=state, **extra
    )


def test_modelos_e_migracoes_dizem_a_mesma_coisa(db_engine):
    # Itens do roteiro (revisão do 2A): o Alembic compara os modelos com o banco migrado e não acha diferença.
    # A tabela `spatial_ref_sys` é do PostGIS e aparece pelo search_path; não é nossa.
    def so_nossas(obj, name, type_, reflected, compare_to):
        return not (type_ == "table" and name == "spatial_ref_sys")

    with db_engine.connect() as conn:
        contexto = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True, "include_object": so_nossas}
        )
        assert compare_metadata(contexto, Base.metadata) == []


def test_cobranca_guarda_o_codigo_do_pix_e_comeca_vazio(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    session.add(
        PixChargeRow(
            charge_id="ch-1", ride_id="ride-1", rider_id="r1", amount_cents=700, rider_cents=600,
            company_cents=100, debt_paid_cents=0,
        )
    )
    session.flush()
    assert session.get(PixChargeRow, "ch-1").br_code == ""
    session.get(PixChargeRow, "ch-1").br_code = "00020126..."
    session.flush()
    session.expire_all()
    assert session.get(PixChargeRow, "ch-1").br_code == "00020126..."


def test_corrida_e_cotacao_guardam_a_rota_e_a_oferta_guarda_o_tempo_de_chegada(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1", route=[[-12.96, -39.26], [-12.95, -39.25]]))
    session.add(
        QuoteRow(
            id="q-1", passenger_id="p1", pickup_lat=0, pickup_lng=0, dest_lat=1, dest_lng=1, distance_m=100,
            duration_s=30, price_cents=500, factor=1.0, reason="x", created_at=1.0, expires_at=2.0,
            route=[[0, 0], [1, 1]],
        )
    )
    session.flush()
    session.add(
        RideOfferRow(ride_id="ride-1", rider_id="r1", created_at=1.0, expires_at=16.0, eta_seconds=95)
    )
    session.flush()
    session.expire_all()
    assert session.get(RideRow, "ride-1").route == [[-12.96, -39.26], [-12.95, -39.25]]
    assert session.get(QuoteRow, "q-1").route == [[0, 0], [1, 1]]
    assert session.get(RideRow, "ride-1").pickup_lat is None      # corrida sem rota continua válida
    assert session.query(RideOfferRow).one().eta_seconds == 95


def test_passageiro_guarda_um_contato_de_emergencia(session):
    add_passenger(session)
    perfil = session.get(PassengerProfileRow, "p1")
    assert (perfil.emergency_name, perfil.emergency_phone) == (None, None)
    perfil.emergency_name, perfil.emergency_phone = "Maria", "+5575988887777"
    session.flush()
    session.expire_all()
    assert session.get(PassengerProfileRow, "p1").emergency_phone == "+5575988887777"


def test_corrida_nao_aponta_para_cobranca_que_nao_existe(session):
    add_passenger(session)
    session.add(_ride("ride-1", current_charge_id="ch-fantasma"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_so_uma_corrida_aberta_por_passageiro(session):
    add_passenger(session)
    session.add(_ride("ride-1", state="searching"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_ride("ride-2", state="accepted"))
            session.flush()


@pytest.mark.parametrize("estado", ["completed", "cancelled", "no_rider"])
def test_corrida_terminada_nao_conta_como_aberta(session, estado):
    add_passenger(session)
    session.add(_ride("ride-1", state=estado))
    session.add(_ride("ride-2", state="searching"))
    session.add(_ride("ride-3", state=estado))
    session.flush()


def test_indices_de_consulta_existem(session):
    nomes = set(
        session.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")).scalars()
    )
    assert {
        "ix_rides_state", "ix_rides_passenger_state", "ix_rides_rider_state", "ix_ride_offers_ride_id",
        "ride_one_open_per_passenger",
    } <= nomes
