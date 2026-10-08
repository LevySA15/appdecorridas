import dataclasses

import pytest

from app.domain.ledger import Ledger
from app.domain.payments import Split, compute_split


def _ledger_com_corrida() -> Ledger:
    ledger = Ledger()
    ledger.post_ride_payment("ride-1", "rider-1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_de_corrida_fecha_em_zero():
    ledger = _ledger_com_corrida()
    assert ledger.is_balanced() is True
    assert ledger.balance("rider:rider-1") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -700


def test_divisao_que_nao_fecha_com_o_preco_e_recusada():
    with pytest.raises(ValueError, match="divisão"):
        Ledger().post_ride_payment("ride-1", "rider-1", 700, Split(500, 100, 0))


def test_pagamento_lancado_duas_vezes_e_recusado():
    # Review Focus 2: o mesmo pagamento nao pode entrar duas vezes no livro.
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_ride_payment("ride-1", "rider-1", 700, compute_split(700, 100))


def test_estorno_zera_os_saldos():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == 0
    assert ledger.is_balanced() is True


def test_estorno_duplo_e_recusado():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    with pytest.raises(ValueError, match="já devolvido"):
        ledger.post_refund("ride-1")


def test_estorno_de_corrida_sem_pagamento_e_recusado():
    with pytest.raises(ValueError, match="não encontrado"):
        Ledger().post_refund("ride-9")


def test_taxa_de_entrada():
    ledger = Ledger()
    ledger.post_entry_fee("rider-1", 5000)
    assert ledger.balance(Ledger.COMPANY) == 5000
    assert ledger.balance(Ledger.PROVIDER) == -5000
    assert ledger.is_balanced() is True
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_entry_fee("rider-1", 5000)


def test_lancamentos_sao_imutaveis_e_a_lista_e_uma_copia():
    ledger = _ledger_com_corrida()
    entry = ledger.entries[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.amount_cents = 1  # type: ignore[misc]
    assert isinstance(ledger.entries, tuple)
    assert len(ledger.entries) == 3


def test_correcao_balanceada_e_registrada():
    ledger = _ledger_com_corrida()
    ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "ajuste de taxa")
    assert ledger.balance(Ledger.COMPANY) == 50
    assert ledger.balance("rider:rider-1") == 650
    assert ledger.is_balanced() is True


def test_correcao_que_nao_fecha_em_zero_e_recusada():
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="zero"):
        ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50)], "erro")


def test_correcao_sem_motivo_ou_de_referencia_desconhecida_e_recusada():
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="motivo"):
        ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], " ")
    with pytest.raises(ValueError, match="desconhecida"):
        ledger.post_correction("ride:nao-existe", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "x")


def test_conciliacao_sem_diferenca():
    assert _ledger_com_corrida().reconcile({"ride:ride-1": 700}) == {}


def test_conciliacao_aponta_diferencas():
    ledger = _ledger_com_corrida()
    assert ledger.reconcile({"ride:ride-1": 600}) == {"ride:ride-1": -100}
    assert ledger.reconcile({}) == {"ride:ride-1": -700}
    assert ledger.reconcile({"ride:ride-1": 700, "ride:ride-9": 500}) == {"ride:ride-9": 500}


def test_conciliacao_depois_de_estorno_nao_acusa_diferenca():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    assert ledger.reconcile({}) == {}
