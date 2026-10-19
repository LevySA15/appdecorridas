import pytest

from app.domain.config import RideConfig
from app.domain.rides import approach_progress, late_cancel_fee_cents


@pytest.mark.parametrize(
    "progress, esperado", [(0.0, 300), (1.0, 500), (0.5, 400), (0.33, 370), (0.75, 450), (None, 300)]
)
def test_taxa_cresce_com_a_distancia_andada(progress, esperado):
    assert late_cancel_fee_cents(progress) == esperado


def test_taxa_respeita_os_limites_mesmo_com_progresso_fora_da_faixa():
    assert late_cancel_fee_cents(-0.4) == 300
    assert late_cancel_fee_cents(7.0) == 500


def test_taxa_segue_os_parametros_do_banco():
    cfg = RideConfig(cancel_fee_min_cents=200, cancel_fee_max_cents=600, cancel_fee_round_cents=50)
    assert late_cancel_fee_cents(0.0, cfg) == 200
    assert late_cancel_fee_cents(1.0, cfg) == 600
    assert late_cancel_fee_cents(0.3, cfg) == 300       # 200 + 400 * 0,3 = 320, arredonda para 300


@pytest.mark.parametrize(
    "inicio, agora, esperado",
    [(2000, 500, 0.75), (2000, 2500, 0.0), (2000, 0, 1.0), (40, 40, 1.0), (None, 300, None), (2000, None, None)],
)
def test_progresso_da_aproximacao(inicio, agora, esperado):
    assert approach_progress(inicio, agora) == esperado
