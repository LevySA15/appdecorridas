import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import PixChargeRow, RatingRow, RideOfferRow, RideRow, RiderProfileRow
from tests.helpers_db import add_passenger, add_rider


def _ride(ride_id: str, passenger_id: str = "p1", state: str = "searching") -> RideRow:
    return RideRow(
        id=ride_id, passenger_id=passenger_id, price_cents=700, payment_method="pix", pin="4821", state=state
    )


def _offer(ride_id: str, rider_id: str, status: str = "pending") -> RideOfferRow:
    return RideOfferRow(
        ride_id=ride_id, rider_id=rider_id, status=status, will_queue=False, created_at=10.0, expires_at=25.0
    )


def test_so_uma_oferta_pendente_por_corrida(session):
    add_passenger(session)
    add_rider(session)
    add_rider(session, "r2", "+5575900000009", "222.222.222-22", "CNH0002", "BBB2B22")
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_offer("ride-1", "r1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-1", "r2"))
            session.flush()


def test_so_uma_oferta_pendente_por_motoqueiro(session):
    add_passenger(session)
    add_rider(session)
    session.add_all([_ride("ride-1"), _ride("ride-2")])
    session.flush()
    session.add(_offer("ride-1", "r1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-2", "r1"))
            session.flush()


def test_oferta_nova_depois_da_anterior_recusada(session):
    add_passenger(session)
    add_rider(session)
    add_rider(session, "r2", "+5575900000009", "222.222.222-22", "CNH0002", "BBB2B22")
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_offer("ride-1", "r1", status="declined"))
    session.add(_offer("ride-1", "r2", status="pending"))
    session.flush()


def test_status_de_oferta_invalido_e_recusado(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-1", "r1", status="talvez"))
            session.flush()


def test_nota_vai_de_1_a_5_e_e_uma_por_pessoa_e_corrida(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1", state="completed"))
    session.flush()
    for ruim in (0, 6):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=ruim, created_at=1.0))
                session.flush()
    session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=5, created_at=1.0))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=4, created_at=2.0))
            session.flush()


def _charge(charge_id: str, ride_id: str | None, purpose: str) -> PixChargeRow:
    return PixChargeRow(
        charge_id=charge_id, ride_id=ride_id, rider_id="r1", amount_cents=5000,
        rider_cents=0, company_cents=5000, debt_paid_cents=0, purpose=purpose,
    )


def test_cobranca_de_entrada_pode_ficar_sem_corrida_mas_as_outras_nao(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_charge("ch-entry", None, "entry"))
    session.add(_charge("ch-ride", "ride-1", "ride"))
    session.flush()
    for finalidade in ("ride", "end"):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(_charge(f"ch-{finalidade}-sem-corrida", None, finalidade))
                session.flush()


def test_finalidade_de_cobranca_invalida_e_recusada(session):
    add_passenger(session)
    add_rider(session)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_charge("ch-x", None, "outra"))
            session.flush()


def test_campos_novos_da_corrida_e_do_motoqueiro_gravam_e_voltam(session):
    add_passenger(session)
    add_rider(session)
    ride = _ride("ride-1")
    ride.pickup_lat, ride.pickup_lng = -12.9, -39.2
    ride.dest_lat, ride.dest_lng = -12.91, -39.21
    ride.pickup_text, ride.dest_text = "Rua A", "Feira livre"
    ride.distance_m, ride.price_factor, ride.price_reason = 2100, 1.1, "Preço normal"
    ride.fee_cents, ride.completed_at = 100, 99.5
    session.add(ride)
    profile = session.get(RiderProfileRow, "r1")
    profile.online = True
    profile.cnh_expires_on = dt.date(2030, 1, 1)
    profile.rating_sum, profile.rating_count = 9, 2
    session.flush()
    session.expire_all()
    assert session.get(RideRow, "ride-1").dest_text == "Feira livre"
    assert session.get(RiderProfileRow, "r1").cnh_expires_on == dt.date(2030, 1, 1)
