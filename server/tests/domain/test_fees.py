import pytest

from app.domain.config import FeeConfig, FeeTier
from app.domain.fees import (
    RiderAccount,
    can_receive_cash_offers,
    can_receive_offers,
    fee_for_ride,
    mark_entry_paid,
    offer_block_reason,
    register_completed_ride,
    validate_fee_config,
)
from app.domain.types import PaymentMethod


def test_taxa_por_faixa_do_dia():
    assert fee_for_ride(1) == 100
    assert fee_for_ride(5) == 100
    assert fee_for_ride(6) == 90
    assert fee_for_ride(10) == 90
    assert fee_for_ride(11) == 80
    assert fee_for_ride(50) == 80


def test_numero_de_corrida_invalido():
    with pytest.raises(ValueError):
        fee_for_ride(0)


def test_config_padrao_e_valida():
    validate_fee_config(FeeConfig())


def test_faixa_abaixo_do_piso_de_lucro_e_invalida():
    cfg = FeeConfig(tiers=(FeeTier(1, None, 60),), min_fee_cents=70)
    with pytest.raises(ValueError, match="piso"):
        validate_fee_config(cfg)


def test_faixas_com_buraco_sao_invalidas():
    cfg = FeeConfig(tiers=(FeeTier(1, 5, 100), FeeTier(7, None, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_ultima_faixa_precisa_ser_aberta():
    cfg = FeeConfig(tiers=(FeeTier(1, 5, 100), FeeTier(6, 10, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_faixa_aberta_so_pode_ser_a_ultima():
    cfg = FeeConfig(tiers=(FeeTier(1, None, 100), FeeTier(6, None, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_as_dez_corridas_de_teste_nao_bloqueiam_e_a_decima_primeira_sim():
    acc = RiderAccount("r1", completed_rides=9)
    assert can_receive_offers(acc) is True
    acc.completed_rides = 10
    assert can_receive_offers(acc) is False
    assert offer_block_reason(acc) == "entrada_pendente"


def test_pagar_a_entrada_libera():
    acc = RiderAccount("r1", completed_rides=10)
    mark_entry_paid(acc)
    assert can_receive_offers(acc) is True
    assert offer_block_reason(acc) is None


def test_corrida_em_dinheiro_vira_divida_e_pix_nao():
    acc = RiderAccount("r1")
    register_completed_ride(acc, PaymentMethod.CASH, 100)
    assert acc.cash_debt_cents == 100
    register_completed_ride(acc, PaymentMethod.PIX, 100)
    assert acc.cash_debt_cents == 100
    assert acc.completed_rides == 2


def test_corrida_em_dinheiro_paga_pelo_qr_do_fim_nao_vira_divida():
    # Review final, item 7: se o QR do fim ja dividiu o pagamento, a taxa ja foi cobrada.
    acc = RiderAccount("r1")
    register_completed_ride(acc, PaymentMethod.CASH, 100, fee_collected_by_split=True)
    assert acc.cash_debt_cents == 0
    assert acc.completed_rides == 1


def test_limite_de_divida_bloqueia_so_corridas_em_dinheiro():
    acc = RiderAccount("r1", cash_debt_cents=999)
    assert can_receive_cash_offers(acc) is True
    acc.cash_debt_cents = 1000
    assert can_receive_cash_offers(acc) is False
    assert can_receive_offers(acc) is True


def test_entrada_pendente_bloqueia_tambem_o_dinheiro():
    acc = RiderAccount("r1", completed_rides=10)
    assert can_receive_cash_offers(acc) is False


def test_limite_de_abatimento_fora_de_0_a_1_e_invalido():
    for ruim in (-0.1, 1.5):
        with pytest.raises(ValueError, match="abatimento"):
            validate_fee_config(FeeConfig(max_debt_share=ruim))
