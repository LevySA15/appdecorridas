import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.fees import RiderAccount
from app.domain.payments import DebtState, compute_split
from app.domain.rides import PassengerAccount, confirm_pix_paid
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_motoqueiro_novo_comeca_sem_corridas_nem_divida(session):
    add_rider(session)
    assert repo.get_rider_account(session, "r1") == RiderAccount("r1")


def test_conta_do_motoqueiro_vai_e_volta(session):
    add_rider(session)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 11
    acc.entry_paid = True
    acc.cash_debt_cents = 500
    acc.debt_reserved_cents = 200
    repo.save_rider_account(session, acc)
    session.expire_all()
    assert repo.get_rider_account(session, "r1") == acc


def test_motoqueiro_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_rider_account(session, "ninguem")


def test_conta_do_passageiro_vai_e_volta(session):
    add_passenger(session)
    assert repo.get_passenger_account(session, "p1") == PassengerAccount("p1")
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    session.expire_all()
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 700


def test_corrida_vai_e_volta_com_todos_os_campos(session):
    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session, busy=True)  # fica na fila
    session.expire_all()
    assert repo.get_ride(session, "ride-1") == ride
    confirm_pix_paid(ride)
    repo.save_ride(session, ride)
    session.expire_all()
    carregada = repo.get_ride(session, "ride-1")
    assert carregada == ride
    assert carregada.pix_paid is True


def test_corrida_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_ride(session, "nao-existe")


def test_cobranca_atual_da_corrida(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    assert repo.get_current_charge_id(session, "ride-1") is None
    repo.set_current_charge(session, "ride-1", "ch-1")
    assert repo.get_current_charge_id(session, "ride-1") == "ch-1"
    repo.set_current_charge(session, "ride-1", None)
    assert repo.get_current_charge_id(session, "ride-1") is None


def test_cobranca_vai_e_volta(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 300))
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge
    charge.paid = True
    charge.refunded = True
    charge.debt_state = DebtState.RESTORED
    repo.save_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge


def test_cobranca_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_charge(session, "ch-99")


def test_evento_so_conta_a_primeira_vez(session):
    # Review Focus 1: a trava contra aviso repetido é uma chave única no banco.
    assert repo.first_time_event(session, "evt-1") is True
    assert repo.first_time_event(session, "evt-1") is False
    assert repo.first_time_event(session, "evt-2") is True
