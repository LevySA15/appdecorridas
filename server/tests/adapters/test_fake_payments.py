import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.domain.payments import PaymentProviderError, RefundUndeliverable, Split, compute_split


def test_cada_cobranca_falsa_tem_codigo_proprio_com_o_valor():
    provider = FakePaymentProvider()
    a = provider.create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
    b = provider.create_pix_charge("ride-2", "r1", 900, compute_split(900, 100, 0))
    assert a.br_code != b.br_code
    assert a.br_code == f"fake-pix|{a.charge_id}|700"


def _paga(provider, valor=700):
    charge = provider.create_pix_charge("ride-1", "r1", valor, compute_split(valor, 100, 0))
    provider.mark_paid(charge.charge_id)
    return charge


def test_devolucao_parcial_acumula_e_so_marca_devolvida_quando_acaba():
    provider = FakePaymentProvider()
    charge = _paga(provider)
    provider.refund(charge.charge_id, 300)
    assert (charge.refunded_cents, charge.refunded) == (300, False)
    provider.refund(charge.charge_id, 400)
    assert (charge.refunded_cents, charge.refunded) == (700, True)


def test_devolucao_sem_valor_devolve_tudo_como_antes():
    provider = FakePaymentProvider()
    charge = _paga(provider)
    provider.refund(charge.charge_id)
    assert (charge.refunded_cents, charge.refunded) == (700, True)


@pytest.mark.parametrize("valor", [0, -5, 701])
def test_devolucao_de_valor_invalido_e_recusada_sem_mudar_nada(valor):
    provider = FakePaymentProvider()
    charge = _paga(provider)
    with pytest.raises(ValueError):
        provider.refund(charge.charge_id, valor)
    assert charge.refunded_cents == 0


def test_nao_devolve_mais_do_que_sobrou():
    provider = FakePaymentProvider()
    charge = _paga(provider)
    provider.refund(charge.charge_id, 500)
    with pytest.raises(ValueError):
        provider.refund(charge.charge_id, 300)


def test_devolucao_que_nao_chega_nao_altera_a_cobranca_por_cobranca_ou_para_todas():
    provider = FakePaymentProvider()
    a, b = _paga(provider), _paga(provider)
    provider.undeliverable.add(a.charge_id)
    with pytest.raises(RefundUndeliverable):
        provider.refund(a.charge_id, 100)
    assert (a.refunded_cents, a.refunded) == (0, False)
    provider.refund(b.charge_id, 100)                           # a outra cobrança segue normal
    provider.refund_all_undeliverable = True
    with pytest.raises(RefundUndeliverable):
        provider.refund(b.charge_id, 100)
    assert b.refunded_cents == 100


def test_cobranca_de_recarga_guarda_de_quem_e_o_saldo():
    provider = FakePaymentProvider()
    charge = provider.create_pix_charge("", "", 2000, Split(0, 2000, 0), purpose="topup", passenger_id="p1")
    assert (charge.purpose, charge.passenger_id, charge.rider_id, charge.ride_id) == ("topup", "p1", "", "")


def test_payout_registra_e_devolve_referencia():
    provider = FakePaymentProvider()
    ref = provider.payout("w1", "52998224725", 1500)
    assert ref == "fake-payout-w1"
    assert provider.payouts == {"w1": ("52998224725", 1500)}


def test_payout_repetido_nao_paga_duas_vezes():
    provider = FakePaymentProvider()
    primeira = provider.payout("w1", "52998224725", 1500)
    segunda = provider.payout("w1", "52998224725", 1500)
    assert primeira == segunda
    assert provider.payouts == {"w1": ("52998224725", 1500)}


def test_payout_com_provedor_fora_do_ar_levanta_erro_de_pagamento_e_nao_registra():
    provider = FakePaymentProvider()
    provider.fail_payouts = True
    with pytest.raises(PaymentProviderError):
        provider.payout("w1", "52998224725", 1500)
    assert provider.payouts == {}


def test_payout_de_valor_nao_positivo_e_recusado():
    with pytest.raises(ValueError, match="positivo"):
        FakePaymentProvider().payout("w1", "52998224725", 0)
