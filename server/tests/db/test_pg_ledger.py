import pytest
from sqlalchemy import text

from app.db.models import LedgerRow
from app.db.pg_ledger import PgLedger
from app.domain.payments import Split, compute_split


def _com_cobranca(session) -> PgLedger:
    ledger = PgLedger(session)
    ledger.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_fecha_em_zero_e_os_saldos_batem(session):
    ledger = _com_cobranca(session)
    assert ledger.is_balanced() is True
    assert ledger.balance("rider:rider-1") == 600
    assert ledger.balance(PgLedger.COMPANY) == 100
    assert ledger.balance(PgLedger.PROVIDER) == -700


def test_um_segundo_objeto_enxerga_o_que_o_primeiro_gravou(session):
    _com_cobranca(session)
    outro = PgLedger(session)
    assert outro.balance("rider:rider-1") == 600
    with pytest.raises(ValueError, match="já lançado"):
        outro.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))


def test_divisao_que_nao_fecha_e_recusada_e_nada_e_gravado(session):
    ledger = PgLedger(session)
    with pytest.raises(ValueError, match="divisão"):
        ledger.post_charge_payment("ch-1", "rider-1", 700, Split(500, 100, 0))
    assert session.execute(text("SELECT count(*) FROM ledger_entries")).scalar() == 0


def test_estorno_zera_os_saldos(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == 0
    assert ledger.is_balanced() is True


def test_estorno_duplo_e_estorno_sem_pagamento_sao_recusados(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    with pytest.raises(ValueError, match="já devolvida"):
        ledger.post_refund("ch-1")
    with pytest.raises(ValueError, match="não encontrado"):
        ledger.post_refund("ch-9")


def test_corrida_que_troca_de_moto_tem_duas_cobrancas_no_livro(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    ledger.post_charge_payment("ch-2", "rider-2", 700, compute_split(700, 100))
    assert ledger.balance("rider:rider-2") == 600
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.is_balanced() is True


def test_taxa_de_entrada_e_so_uma_vez(session):
    ledger = PgLedger(session)
    ledger.post_entry_fee("rider-1", 5000)
    assert ledger.balance(PgLedger.COMPANY) == 5000
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_entry_fee("rider-1", 5000)


def test_correcao_balanceada_e_registrada(session):
    ledger = _com_cobranca(session)
    ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], "ajuste de taxa")
    assert ledger.balance(PgLedger.COMPANY) == 50
    assert ledger.balance("rider:rider-1") == 650
    assert ledger.is_balanced() is True


def test_correcoes_invalidas_sao_recusadas(session):
    ledger = _com_cobranca(session)
    with pytest.raises(ValueError, match="zero"):
        ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50)], "erro")
    with pytest.raises(ValueError, match="motivo"):
        ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], " ")
    with pytest.raises(ValueError, match="desconhecida"):
        ledger.post_correction("charge:nao-existe", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], "x")


def test_conciliacao_aponta_diferencas(session):
    ledger = _com_cobranca(session)
    assert ledger.reconcile({"charge:ch-1": 700}) == {}
    assert ledger.reconcile({"charge:ch-1": 600}) == {"charge:ch-1": -100}
    assert ledger.reconcile({}) == {"charge:ch-1": -700}
    assert ledger.reconcile({"charge:ch-1": 700, "charge:ch-9": 500}) == {"charge:ch-9": 500}


def test_conciliacao_depois_de_estorno_nao_acusa_diferenca(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    assert ledger.reconcile({}) == {}


def test_lancamento_solto_que_nao_fecha_e_detectado(session):
    ledger = PgLedger(session)
    session.add(LedgerRow(ref="charge:ch-x", account="company", amount_cents=100, kind="ride_payment"))
    session.flush()
    assert ledger.is_balanced() is False
