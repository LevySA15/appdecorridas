import pytest

from app.domain.balance import (
    CancelFee,
    FeePlan,
    apply_pending_payment,
    credit,
    plan_fee_collection,
    spend_up_to,
    waive_pending,
)
from app.domain.rides import PassengerAccount


def test_gastar_do_saldo_nunca_passa_do_que_tem():
    acc = PassengerAccount("p1", balance_cents=100)
    assert spend_up_to(acc, 400) == 100
    assert acc.balance_cents == 0
    assert spend_up_to(acc, 400) == 0


def test_gastar_do_saldo_so_o_que_pediu():
    acc = PassengerAccount("p1", balance_cents=1000)
    assert spend_up_to(acc, 400) == 400
    assert acc.balance_cents == 600


@pytest.mark.parametrize("valor", [0, -5])
def test_credito_zero_ou_negativo_e_recusado(valor):
    acc = PassengerAccount("p1")
    with pytest.raises(ValueError):
        credit(acc, valor)
    assert acc.balance_cents == 0


def test_gasto_negativo_e_recusado():
    with pytest.raises(ValueError):
        spend_up_to(PassengerAccount("p1", balance_cents=100), -1)


def test_credito_soma_no_saldo():
    acc = PassengerAccount("p1", balance_cents=50)
    credit(acc, 250)
    assert acc.balance_cents == 300


@pytest.mark.parametrize(
    "saldo, taxa, retido_pelo_pix, esperado",
    [
        (1000, 400, 0, FeePlan(400, 0, 0)),
        (100, 400, 0, FeePlan(100, 0, 300)),
        (0, 400, 700, FeePlan(0, 400, 0)),
        (150, 400, 700, FeePlan(150, 250, 0)),
        (0, 500, 500, FeePlan(0, 500, 0)),
        (0, 400, 0, FeePlan(0, 0, 400)),
        (0, 400, 300, FeePlan(0, 300, 100)),
    ],
)
def test_plano_de_cobranca_da_taxa(saldo, taxa, retido_pelo_pix, esperado):
    plano = plan_fee_collection(taxa, saldo, retido_pelo_pix)
    assert plano == esperado
    assert plano.from_balance + plano.retained + plano.pending == taxa


def _taxa(**partes) -> CancelFee:
    base = dict(ride_id="ride-1", passenger_id="p1", rider_id="r1", fee_cents=400, reason="passenger", created_at=1.0)
    return CancelFee(**(base | partes))


def test_perdoar_a_pendencia_zera_e_soma_nos_perdoados():
    taxa = _taxa(from_balance_cents=100, pending_cents=300)
    assert waive_pending(taxa) == 300
    assert (taxa.pending_cents, taxa.waived_cents) == (0, 300)
    assert waive_pending(taxa) == 0


def test_pagamento_da_pendencia_passa_de_pendente_para_pago_depois():
    taxa = _taxa(retained_cents=100, pending_cents=300)
    apply_pending_payment(taxa, 300)
    assert (taxa.pending_cents, taxa.paid_later_cents) == (0, 300)


@pytest.mark.parametrize("valor", [0, -1, 301])
def test_pagamento_invalido_da_pendencia_e_recusado(valor):
    taxa = _taxa(retained_cents=100, pending_cents=300)
    with pytest.raises(ValueError):
        apply_pending_payment(taxa, valor)
    assert taxa.pending_cents == 300
