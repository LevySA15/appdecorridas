import dataclasses

import pytest

from app.domain.ledger import Ledger
from app.domain.payments import Split, compute_split


def _ledger_com_cobranca() -> Ledger:
    ledger = Ledger()
    ledger.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_de_cobranca_fecha_em_zero():
    ledger = _ledger_com_cobranca()
    assert ledger.is_balanced() is True
    assert ledger.balance("rider:rider-1") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -700


def test_divisao_que_nao_fecha_com_o_preco_e_recusada():
    with pytest.raises(ValueError, match="divisão"):
        Ledger().post_charge_payment("ch-1", "rider-1", 700, Split(500, 100, 0))


def test_pagamento_da_mesma_cobranca_lancado_duas_vezes_e_recusado():
    # Review Focus 2: o mesmo pagamento nao pode entrar duas vezes no livro.
    ledger = _ledger_com_cobranca()
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))


def test_corrida_que_troca_de_moto_pode_ter_dois_pagamentos_em_cobrancas_diferentes():
    # Review final, item 2: pagou ch-1, estornou, o passageiro pagou de novo com outra moto (ch-2).
    ledger = _ledger_com_cobranca()
    ledger.post_refund("ch-1")
    ledger.post_charge_payment("ch-2", "rider-2", 700, compute_split(700, 100))
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance("rider:rider-2") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.is_balanced() is True
    ledger.post_refund("ch-2")
    assert ledger.balance("rider:rider-2") == 0
    assert ledger.balance(Ledger.COMPANY) == 0


def test_estorno_zera_os_saldos():
    ledger = _ledger_com_cobranca()
    ledger.post_refund("ch-1")
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == 0
    assert ledger.is_balanced() is True


def test_estorno_duplo_e_recusado():
    ledger = _ledger_com_cobranca()
    ledger.post_refund("ch-1")
    with pytest.raises(ValueError, match="já devolvida"):
        ledger.post_refund("ch-1")


def test_estorno_de_cobranca_sem_pagamento_e_recusado():
    with pytest.raises(ValueError, match="não encontrado"):
        Ledger().post_refund("ch-9")


def test_taxa_de_entrada():
    ledger = Ledger()
    ledger.post_entry_fee("rider-1", 5000)
    assert ledger.balance(Ledger.COMPANY) == 5000
    assert ledger.balance(Ledger.PROVIDER) == -5000
    assert ledger.is_balanced() is True
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_entry_fee("rider-1", 5000)


def test_lancamentos_sao_imutaveis_e_a_lista_e_uma_copia():
    ledger = _ledger_com_cobranca()
    entry = ledger.entries[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.amount_cents = 1  # type: ignore[misc]
    assert isinstance(ledger.entries, tuple)
    assert len(ledger.entries) == 3


def test_correcao_balanceada_e_registrada():
    ledger = _ledger_com_cobranca()
    ledger.post_correction("charge:ch-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "ajuste de taxa")
    assert ledger.balance(Ledger.COMPANY) == 50
    assert ledger.balance("rider:rider-1") == 650
    assert ledger.is_balanced() is True


def test_correcao_que_nao_fecha_em_zero_e_recusada():
    ledger = _ledger_com_cobranca()
    with pytest.raises(ValueError, match="zero"):
        ledger.post_correction("charge:ch-1", [(Ledger.COMPANY, -50)], "erro")


def test_correcao_sem_motivo_ou_de_referencia_desconhecida_e_recusada():
    ledger = _ledger_com_cobranca()
    with pytest.raises(ValueError, match="motivo"):
        ledger.post_correction("charge:ch-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], " ")
    with pytest.raises(ValueError, match="desconhecida"):
        ledger.post_correction("charge:nao-existe", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "x")


def test_conciliacao_sem_diferenca():
    assert _ledger_com_cobranca().reconcile({"charge:ch-1": 700}) == {}


def test_conciliacao_aponta_diferencas():
    ledger = _ledger_com_cobranca()
    assert ledger.reconcile({"charge:ch-1": 600}) == {"charge:ch-1": -100}
    assert ledger.reconcile({}) == {"charge:ch-1": -700}
    assert ledger.reconcile({"charge:ch-1": 700, "charge:ch-9": 500}) == {"charge:ch-9": 500}


def test_conciliacao_depois_de_estorno_nao_acusa_diferenca():
    ledger = _ledger_com_cobranca()
    ledger.post_refund("ch-1")
    assert ledger.reconcile({}) == {}


def test_livro_pode_ser_montado_a_partir_de_lancamentos_existentes():
    original = _ledger_com_cobranca()
    copia = Ledger.from_entries(original.entries)
    assert copia.balance("rider:rider-1") == 600
    with pytest.raises(ValueError, match="já lançado"):
        copia.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))
    copia.post_refund("ch-1")
    assert copia.is_balanced() is True
    assert len(original.entries) == 3  # o original não muda


def test_devolucao_parcial_deixa_a_taxa_com_o_motoqueiro_e_o_resto_volta_ao_provedor():
    ledger = _ledger_com_cobranca()                       # preço 700: motoqueiro 600, empresa 100
    ledger.post_refund("ch-1", keep_cents=400)
    assert ledger.balance("rider:rider-1") == 400
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == -400
    assert ledger.is_balanced() is True


def test_devolucao_parcial_do_valor_inteiro_nao_manda_nada_ao_provedor():
    ledger = Ledger()
    ledger.post_charge_payment("ch-1", "rider-1", 500, compute_split(500, 100))     # motoqueiro 400, empresa 100
    ledger.post_refund("ch-1", keep_cents=500)
    assert ledger.balance("rider:rider-1") == 500
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == -500
    assert ledger.is_balanced() is True


def test_devolucao_para_o_saldo_guarda_o_resto_na_conta_do_passageiro():
    ledger = _ledger_com_cobranca()
    ledger.post_refund_to_balance("ch-1", "p1", keep_cents=400)
    assert ledger.balance(Ledger.balance_account("p1")) == 300
    assert ledger.balance("rider:rider-1") == 400
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == -700           # o dinheiro continua no provedor
    assert ledger.is_balanced() is True


def test_devolucao_inteira_para_o_saldo():
    ledger = _ledger_com_cobranca()
    ledger.post_refund_to_balance("ch-1", "p1")
    assert ledger.balance(Ledger.balance_account("p1")) == 700
    assert ledger.balance("rider:rider-1") == 0 and ledger.balance(Ledger.COMPANY) == 0
    assert ledger.is_balanced() is True


@pytest.mark.parametrize("primeira, segunda", [
    ("pix", "pix"), ("pix", "saldo"), ("saldo", "pix"), ("saldo", "saldo"),
])
def test_devolver_duas_vezes_e_recusado_de_qualquer_jeito(primeira, segunda):
    ledger = _ledger_com_cobranca()

    def devolver(como):
        if como == "pix":
            ledger.post_refund("ch-1")
        else:
            ledger.post_refund_to_balance("ch-1", "p1")

    devolver(primeira)
    with pytest.raises(ValueError, match="já devolvida"):
        devolver(segunda)


@pytest.mark.parametrize("retido", [-1, 701])
def test_parte_retida_fora_do_valor_da_cobranca_e_recusada(retido):
    ledger = _ledger_com_cobranca()
    with pytest.raises(ValueError, match="retida"):
        ledger.post_refund("ch-1", keep_cents=retido)
    assert ledger.is_balanced() is True and ledger.balance(Ledger.PROVIDER) == -700


def test_gasto_do_saldo_paga_o_motoqueiro_e_fecha():
    ledger = Ledger()
    ledger.post_spend_balance("fee:ride-1:cancel", "p1", "rider-1", 450)
    assert ledger.balance(Ledger.balance_account("p1")) == -450
    assert ledger.balance("rider:rider-1") == 450
    assert ledger.is_balanced() is True
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_spend_balance("fee:ride-1:cancel", "p1", "rider-1", 450)


def test_recarga_credita_o_saldo_e_fecha():
    ledger = Ledger()
    ledger.post_topup("ch-9", "p1", 2000)
    assert ledger.balance(Ledger.balance_account("p1")) == 2000
    assert ledger.balance(Ledger.PROVIDER) == -2000
    assert ledger.is_balanced() is True
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_topup("ch-9", "p1", 2000)


def test_credito_da_empresa_ao_passageiro_fecha():
    ledger = Ledger()
    ledger.post_credit_from_company("fee:ride-1:appeal", "p1", 400)
    assert ledger.balance(Ledger.COMPANY) == -400
    assert ledger.balance(Ledger.balance_account("p1")) == 400
    assert ledger.is_balanced() is True


@pytest.mark.parametrize("valor", [0, -10])
def test_lancamentos_do_saldo_recusam_valor_zero_ou_negativo(valor):
    ledger = Ledger()
    with pytest.raises(ValueError, match="positivo"):
        ledger.post_spend_balance("fee:x:cancel", "p1", "rider-1", valor)
    with pytest.raises(ValueError, match="positivo"):
        ledger.post_topup("ch-1", "p1", valor)
    with pytest.raises(ValueError, match="positivo"):
        ledger.post_credit_from_company("fee:x:appeal", "p1", valor)
