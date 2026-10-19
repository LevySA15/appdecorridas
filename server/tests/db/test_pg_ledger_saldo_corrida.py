"""Corrida paga com saldo e saque no livro-caixa gravado no PostgreSQL."""
import pytest

from app.db.pg_ledger import PgLedger
from app.domain.payments import compute_split


def _paga_com_saldo(session) -> PgLedger:
    ledger = PgLedger(session)
    ledger.post_topup("ch-0", "p1", 2000)
    ledger.post_charge_payment_from_balance("bal-1", "p1", "r1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_com_saldo_fecha_em_zero_e_os_saldos_batem(session):
    ledger = _paga_com_saldo(session)
    assert ledger.is_balanced() is True
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (1300, 600, 100)


def test_pagamento_com_saldo_repetido_e_recusado(session):
    _paga_com_saldo(session)
    with pytest.raises(ValueError, match="já lançado"):
        PgLedger(session).post_charge_payment_from_balance("bal-1", "p1", "r1", 700, compute_split(700, 100))


def test_devolucao_com_taxa_retida_volta_para_o_saldo(session):
    ledger = _paga_com_saldo(session)
    ledger.post_refund_to_balance("bal-1", "p1", keep_cents=300)
    assert ledger.is_balanced() is True
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (1700, 300, 0)


def test_pagamento_com_saldo_nao_volta_para_o_provedor(session):
    ledger = _paga_com_saldo(session)
    with pytest.raises(ValueError, match="saldo"):
        ledger.post_refund("bal-1")


def test_saque_tira_do_saldo_e_entra_no_provedor(session):
    ledger = PgLedger(session)
    ledger.post_topup("ch-0", "p1", 2000)
    ledger.post_withdrawal("w1", "p1", 500)
    assert ledger.is_balanced() is True
    assert (ledger.balance("balance:p1"), ledger.balance(PgLedger.PROVIDER)) == (1500, -1500)
    with pytest.raises(ValueError, match="já lançado"):
        PgLedger(session).post_withdrawal("w1", "p1", 500)


def test_extrato_do_provedor_com_saque_confere(session):
    ledger = PgLedger(session)
    ledger.post_topup("ch-0", "p1", 2000)
    ledger.post_withdrawal("w1", "p1", 500)
    assert ledger.reconcile({"charge:ch-0": 2000, "withdraw:w1": -500}) == {}
