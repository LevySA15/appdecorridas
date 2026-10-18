from app.adapters.fake_payments import FakePaymentProvider
from app.domain.payments import compute_split


def test_cada_cobranca_falsa_tem_codigo_proprio_com_o_valor():
    provider = FakePaymentProvider()
    a = provider.create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
    b = provider.create_pix_charge("ride-2", "r1", 900, compute_split(900, 100, 0))
    assert a.br_code != b.br_code
    assert a.br_code == f"fake-pix|{a.charge_id}|700"
