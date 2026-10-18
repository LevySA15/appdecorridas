import pytest

from app.domain.config import RideConfig
from app.domain.fees import RiderAccount, add_cash_fee_debt, count_completed_ride
from app.domain.rides import (
    InvalidTransition,
    PassengerAccount,
    Ride,
    RideState,
    accept,
    block_for_unpaid,
    cash_pay_wait_expired,
    complete,
    confirm_end_payment,
    confirm_helmet,
    confirm_qr_payment,
    mark_arrived,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod


def _concluida(method=PaymentMethod.CASH, now=1000.0) -> Ride:
    ride = Ride("ride-1", "p1", 700, method, pin="4821")
    start_search(ride, 0)
    accept(ride, "r1", 1, rider_busy=False)
    mark_arrived(ride, 2)
    confirm_helmet(ride)
    if method is PaymentMethod.PIX:
        ride.pix_paid = True
    start_ride(ride, "4821")
    complete(ride, now)
    return ride


def test_completar_guarda_o_instante():
    assert _concluida(now=1234.5).completed_at == 1234.5
    ride = Ride("r", "p", 700, PaymentMethod.CASH, pin="4821", state=RideState.IN_PROGRESS)
    complete(ride)  # sem instante continua valendo
    assert ride.completed_at is None


def test_prazo_de_pagamento_em_dinheiro():
    ride = _concluida()
    cfg = RideConfig(cash_pay_wait_s=300)
    assert cash_pay_wait_expired(ride, 1299, cfg) is False
    assert cash_pay_wait_expired(ride, 1300, cfg) is True


def test_prazo_nao_vale_para_pix_nem_para_corrida_ja_paga_ou_ja_bloqueada():
    assert cash_pay_wait_expired(_concluida(PaymentMethod.PIX), 9999) is False
    paga = _concluida()
    confirm_end_payment(paga)
    assert cash_pay_wait_expired(paga, 9999) is False
    bloqueada = _concluida()
    block_for_unpaid(bloqueada, PassengerAccount("p1"), 1300)
    assert cash_pay_wait_expired(bloqueada, 9999) is False


def test_bloqueio_por_falta_de_pagamento_soma_a_divida_do_passageiro():
    ride = _concluida()
    passenger = PassengerAccount("p1")
    block_for_unpaid(ride, passenger, 1300)
    assert passenger.unpaid_cents == 700
    assert ride.non_payment_reported is True
    with pytest.raises(InvalidTransition):
        block_for_unpaid(ride, passenger, 1400)  # só uma vez


def test_bloqueio_antes_do_prazo_e_recusado():
    with pytest.raises(InvalidTransition, match="prazo"):
        block_for_unpaid(_concluida(), PassengerAccount("p1"), 1100)


def test_pagamento_pelo_qr_confirma_a_corrida_mesmo_depois_do_bloqueio():
    ride = _concluida()
    block_for_unpaid(ride, PassengerAccount("p1"), 1300)
    confirm_qr_payment(ride)
    assert ride.end_payment_confirmed is True
    with pytest.raises(InvalidTransition, match="já foi confirmado"):
        confirm_qr_payment(ride)


def test_pagamento_pelo_qr_so_vale_para_corrida_concluida_em_dinheiro():
    with pytest.raises(InvalidTransition):
        confirm_qr_payment(_concluida(PaymentMethod.PIX))
    andando = Ride("r", "p", 700, PaymentMethod.CASH, pin="4821", state=RideState.IN_PROGRESS)
    with pytest.raises(InvalidTransition):
        confirm_qr_payment(andando)


def test_contar_corrida_e_somar_taxa_de_dinheiro_sao_passos_separados():
    acc = RiderAccount("r1")
    count_completed_ride(acc)
    assert (acc.completed_rides, acc.cash_debt_cents) == (1, 0)
    add_cash_fee_debt(acc, 100)
    assert (acc.completed_rides, acc.cash_debt_cents) == (1, 100)
    with pytest.raises(ValueError):
        add_cash_fee_debt(acc, -1)
