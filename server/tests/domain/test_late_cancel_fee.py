import pytest

from app.domain.config import RideConfig
from app.domain.rides import approach_traveled_m, late_cancel_fee_cents


@pytest.mark.parametrize("andados", [0, 150, 299.9])
def test_moto_que_andou_menos_de_300_metros_nao_gera_taxa(andados):
    assert late_cancel_fee_cents(andados) == 0


def test_taxa_comeca_em_3_reais_com_300_metros_andados():
    assert late_cancel_fee_cents(300) == 300


@pytest.mark.parametrize(
    "andados, esperado",
    [(400, 320), (600, 350), (900, 400), (1200, 450), (1500, 500)],
)
def test_taxa_cresce_em_linha_reta_ate_o_maximo_com_1500_metros(andados, esperado):
    assert late_cancel_fee_cents(andados) == esperado


def test_taxa_nao_passa_do_maximo_e_negativo_conta_como_parado():
    assert late_cancel_fee_cents(9000) == 500
    assert late_cancel_fee_cents(-50) == 0


def test_sem_posicao_cobra_o_minimo():
    assert late_cancel_fee_cents(None) == 300


@pytest.mark.parametrize("andados", [None, 0, 100, 5000])
def test_moto_no_ponto_cobra_o_maximo_com_qualquer_distancia(andados):
    assert late_cancel_fee_cents(andados, at_pickup=True) == 500


def test_taxa_segue_os_parametros_do_banco():
    cfg = RideConfig(
        cancel_fee_min_cents=200, cancel_fee_max_cents=600, cancel_fee_round_cents=50,
        cancel_fee_free_m=100, cancel_fee_full_m=500,
    )
    assert late_cancel_fee_cents(99, cfg) == 0
    assert late_cancel_fee_cents(100, cfg) == 200
    assert late_cancel_fee_cents(300, cfg) == 400
    assert late_cancel_fee_cents(500, cfg) == 600
    assert late_cancel_fee_cents(120, cfg) == 200       # 200 + 400 * 0,05 = 220, arredonda para 200
    assert late_cancel_fee_cents(180, cfg) == 300       # 200 + 400 * 0,2 = 280, arredonda para 300


@pytest.mark.parametrize(
    "inicio, agora, esperado",
    [(2000, 500, 1500), (2000, 2500, 0), (2000, 0, 2000), (40, 40, 0), (None, 300, None), (2000, None, None)],
)
def test_metros_andados_na_aproximacao(inicio, agora, esperado):
    assert approach_traveled_m(inicio, agora) == esperado
