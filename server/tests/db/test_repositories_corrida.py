from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.payments import Split
from app.domain.rides import complete, confirm_helmet, mark_arrived, start_ride
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_corrida_guarda_instante_de_conclusao_e_taxa(session):
    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session)
    ride.fee_cents = 90
    mark_arrived(ride, 20)
    confirm_helmet(ride)
    ride.pix_paid = True
    start_ride(ride, "4821")
    complete(ride, 321.5)
    repo.save_ride(session, ride)
    session.expire_all()
    carregada = repo.get_ride(session, "ride-1")
    assert (carregada.completed_at, carregada.fee_cents) == (321.5, 90)
    assert carregada == ride


def test_cobranca_de_entrada_nao_tem_corrida_e_volta_igual(session):
    add_rider(session)
    charge = FakePaymentProvider().create_pix_charge("", "r1", 5000, Split(0, 5000, 0), purpose="entry")
    assert charge.purpose == "entry" and charge.ride_id == ""
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge


def test_cobranca_de_fim_de_corrida_guarda_a_finalidade(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, Split(600, 100, 0), purpose="end")
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id).purpose == "end"
