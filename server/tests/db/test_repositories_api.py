from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.geo import GeoPoint
from app.domain.payments import compute_split
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_codigo_do_pix_vai_e_volta_com_a_cobranca(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
    assert charge.br_code.startswith("fake-pix|")
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id).br_code == charge.br_code


def test_detalhes_da_corrida_guardam_a_rota(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    rota = ((-12.9644, -39.2597), (-12.9600, -39.2500))
    repo.set_ride_details(
        session, "ride-1",
        repo.RideDetails(GeoPoint(-12.9644, -39.2597), GeoPoint(-12.96, -39.25), "A", "B", 1500, 1.0, "normal", route=rota),
    )
    session.expire_all()
    assert repo.get_ride_details(session, "ride-1").route == rota


def test_detalhes_sem_rota_voltam_com_rota_vazia(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    repo.set_ride_details(
        session, "ride-1",
        repo.RideDetails(GeoPoint(-12.9644, -39.2597), GeoPoint(-12.96, -39.25), "A", "B", 1500, 1.0, "normal"),
    )
    session.expire_all()
    assert repo.get_ride_details(session, "ride-1").route == ()


def test_contato_de_emergencia_vai_e_volta(session):
    add_passenger(session)
    assert repo.get_emergency_contact(session, "p1") is None
    repo.set_emergency_contact(session, "p1", "Maria", "+5575988887777")
    session.expire_all()
    assert repo.get_emergency_contact(session, "p1") == repo.EmergencyContact("Maria", "+5575988887777")
    repo.set_emergency_contact(session, "p1", "João", "+5575911112222")
    assert repo.get_emergency_contact(session, "p1").name == "João"
