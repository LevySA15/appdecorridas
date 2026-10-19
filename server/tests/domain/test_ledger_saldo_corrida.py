"""Corrida paga com o saldo do passageiro e saque do saldo no livro-caixa."""
import pytest

from app.domain.ledger import Ledger
from app.domain.payments import compute_split


def _paga_com_saldo() -> Ledger:
    ledger = Ledger()
    ledger.post_topup("ch-0", "p1", 2000)            # o passageiro tinha R$ 20,00 de saldo
    ledger.post_charge_payment_from_balance("bal-1", "p1", "r1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_com_saldo_soma_zero_e_move_o_saldo_para_motoqueiro_e_empresa():
    ledger = _paga_com_saldo()
    assert ledger.is_balanced() is True
    assert ledger.balance("balance:p1") == 1300
    assert ledger.balance("rider:r1") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -2000          # só a recarga passou pelo provedor


def test_pagamento_com_saldo_repetido_e_recusado():
    ledger = _paga_com_saldo()
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_charge_payment_from_balance("bal-1", "p1", "r1", 700, compute_split(700, 100))


def test_divisao_que_nao_fecha_com_o_preco_e_recusada():
    with pytest.raises(ValueError, match="divisão"):
        Ledger().post_charge_payment_from_balance("bal-1", "p1", "r1", 700, compute_split(600, 100))


def test_devolucao_de_pagamento_com_saldo_volta_inteira_para_o_saldo():
    ledger = _paga_com_saldo()
    ledger.post_refund_to_balance("bal-1", "p1")
    assert ledger.is_balanced() is True
    assert ledger.balance("balance:p1") == 2000
    assert ledger.balance("rider:r1") == 0
    assert ledger.balance(Ledger.COMPANY) == 0


def test_devolucao_com_taxa_retida_deixa_a_taxa_com_o_motoqueiro():
    ledger = _paga_com_saldo()
    ledger.post_refund_to_balance("bal-1", "p1", keep_cents=300)
    assert ledger.is_balanced() is True
    assert ledger.balance("balance:p1") == 1700           # 1300 + (700 - 300)
    assert ledger.balance("rider:r1") == 300
    assert ledger.balance(Ledger.COMPANY) == 0


def test_pagamento_com_saldo_nao_volta_para_o_provedor():
    ledger = _paga_com_saldo()
    with pytest.raises(ValueError, match="saldo"):
        ledger.post_refund("bal-1")


def test_pagamento_com_saldo_nao_e_devolvido_duas_vezes():
    ledger = _paga_com_saldo()
    ledger.post_refund_to_balance("bal-1", "p1")
    with pytest.raises(ValueError, match="já devolvida"):
        ledger.post_refund_to_balance("bal-1", "p1")


def test_pagamento_pix_continua_devolvendo_para_o_provedor_e_para_o_saldo():
    pix = Ledger()
    pix.post_charge_payment("ch-1", "r1", 700, compute_split(700, 100))
    pix.post_refund("ch-1")
    assert pix.balance(Ledger.PROVIDER) == 0 and pix.is_balanced() is True
    outro = Ledger()
    outro.post_charge_payment("ch-2", "r1", 700, compute_split(700, 100))
    outro.post_refund_to_balance("ch-2", "p1", keep_cents=300)
    assert outro.balance("balance:p1") == 400
    assert outro.balance(Ledger.PROVIDER) == -700 and outro.is_balanced() is True


def test_saque_tira_do_saldo_e_entra_no_provedor():
    ledger = Ledger()
    ledger.post_topup("ch-0", "p1", 2000)
    ledger.post_withdrawal("w1", "p1", 500)
    assert ledger.is_balanced() is True
    assert ledger.balance("balance:p1") == 1500
    assert ledger.balance(Ledger.PROVIDER) == -1500


def test_saque_repetido_ou_nao_positivo_e_recusado():
    ledger = Ledger()
    ledger.post_withdrawal("w1", "p1", 500)
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_withdrawal("w1", "p1", 500)
    for valor in (0, -5):
        with pytest.raises(ValueError, match="positivo"):
            ledger.post_withdrawal("w2", "p1", valor)


def test_extrato_do_provedor_com_saque_confere():
    ledger = Ledger()
    ledger.post_topup("ch-0", "p1", 2000)
    ledger.post_withdrawal("w1", "p1", 500)
    assert ledger.reconcile({"charge:ch-0": 2000, "withdraw:w1": -500}) == {}
