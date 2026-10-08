import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.domain.fees import RiderAccount
from app.domain.payments import ProcessedEvents, Split, compute_split, settle_pix_ride


def test_divisao_sem_divida():
    assert compute_split(700, 100) == Split(rider_cents=600, company_cents=100, debt_paid_cents=0)


def test_divisao_com_divida_pequena_abate_tudo():
    assert compute_split(700, 100, 300) == Split(rider_cents=300, company_cents=400, debt_paid_cents=300)


def test_divisao_limita_o_desconto_da_divida_a_metade_do_ganho():
    # Review Focus 1: divida (1000) maior que o ganho (600): o motoqueiro nao fica com R$ 0,00.
    split = compute_split(700, 100, 1000)
    assert split == Split(rider_cents=300, company_cents=400, debt_paid_cents=300)


def test_divisao_com_limite_configuravel():
    split = compute_split(700, 100, 1000, max_debt_share=1.0)
    assert split == Split(rider_cents=0, company_cents=700, debt_paid_cents=600)


def test_divisao_taxa_maior_que_o_preco_da_erro():
    with pytest.raises(ValueError):
        compute_split(100, 200)


def test_divisao_preco_zero_ou_negativo_da_erro():
    with pytest.raises(ValueError):
        compute_split(0, 0)
    with pytest.raises(ValueError):
        compute_split(-5, 0)


def test_divisao_soma_sempre_o_preco():
    for debt in (0, 50, 300, 5000):
        s = compute_split(950, 90, debt)
        assert s.rider_cents + s.company_cents == 950


def test_settle_pix_ride_abate_a_divida_da_conta():
    acc = RiderAccount("r1", cash_debt_cents=1000)
    split = settle_pix_ride(acc, 700, 100)
    assert split.debt_paid_cents == 300
    assert acc.cash_debt_cents == 700


def test_evento_repetido_so_vale_uma_vez():
    # Review Focus 2: aviso repetido do provedor nao pode ser tratado duas vezes.
    events = ProcessedEvents()
    assert events.first_time("e1") is True
    assert events.first_time("e1") is False
    assert events.first_time("e2") is True


def test_provedor_falso_cria_e_paga_cobranca():
    provider = FakePaymentProvider()
    charge = provider.create_pix_charge("ride-1", "rider-1", 700, compute_split(700, 100))
    assert charge.charge_id == "ch-1"
    assert charge.paid is False
    event = provider.mark_paid("ch-1")
    assert event == {
        "event_id": "evt-ch-1-paid",
        "type": "paid",
        "charge_id": "ch-1",
        "ride_id": "ride-1",
        "amount_cents": 700,
    }
    assert provider.charges["ch-1"].paid is True


def test_provedor_falso_so_estorna_cobranca_paga_e_uma_vez():
    provider = FakePaymentProvider()
    provider.create_pix_charge("ride-1", "rider-1", 700, compute_split(700, 100))
    with pytest.raises(ValueError, match="não paga"):
        provider.refund("ch-1")
    provider.mark_paid("ch-1")
    provider.refund("ch-1")
    assert provider.charges["ch-1"].refunded is True
    with pytest.raises(ValueError, match="já devolvida"):
        provider.refund("ch-1")


def test_provedor_falso_recusa_divisao_que_nao_fecha():
    provider = FakePaymentProvider()
    with pytest.raises(ValueError, match="divisão"):
        provider.create_pix_charge("ride-1", "rider-1", 700, Split(100, 100, 0))
