from app.domain.safety import (
    AlertType,
    PositionSample,
    clean_samples,
    evaluate,
    speed_kmh,
)
from tests.helpers import pt

ROUTE = [pt(0, 0), pt(5000, 0)]  # reta para o norte


def walk(n: int, step_m: float = 100.0, dt: float = 10.0) -> list[PositionSample]:
    """`n` amostras andando pela rota para o norte: 100 m a cada 10 s = 36 km/h."""
    return [PositionSample(pt(i * step_m, 0), i * dt) for i in range(n)]


def test_velocidade_em_kmh():
    a, b = PositionSample(pt(0, 0), 0), PositionSample(pt(100, 0), 10)
    assert round(speed_kmh(a, b)) == 36


def test_andando_pela_rota_nao_gera_alerta():
    result = evaluate(walk(30), ROUTE)
    assert result.alert is None
    assert result.suspected_mock_location is False


def test_parada_por_mais_de_3_minutos_gera_alerta():
    samples = walk(10) + [PositionSample(pt(900, 0), 100 + i * 10) for i in range(22)]
    assert evaluate(samples, ROUTE).alert is AlertType.STOPPED


def test_parada_curta_nao_gera_alerta():
    samples = walk(10) + [PositionSample(pt(900, 0), 100 + i * 10) for i in range(10)]
    assert evaluate(samples, ROUTE).alert is None


def test_pouco_historico_nao_gera_alerta_de_parada():
    assert evaluate([PositionSample(pt(0, 0), 0)], ROUTE).alert is None


def test_fora_da_rota_exige_tres_amostras_seguidas():
    base = walk(10)  # termina em t=90, em (900, 0)
    off1 = PositionSample(pt(900, 400), 110)
    off2 = PositionSample(pt(900, 800), 130)
    off3 = PositionSample(pt(900, 1200), 150)
    assert evaluate(base + [off1, off2], ROUTE).alert is None
    assert evaluate(base + [off1, off2, off3], ROUTE).alert is AlertType.OFF_ROUTE


def test_um_salto_de_gps_e_ignorado():
    samples = walk(10) + [PositionSample(pt(900, 50_000), 100), PositionSample(pt(1000, 0), 110)]
    good, jumps = clean_samples(samples)
    assert jumps == 1
    assert good[-1].t == 110
    result = evaluate(samples, ROUTE)
    assert result.alert is None
    assert result.suspected_mock_location is False


def test_dois_saltos_marcam_suspeita_de_localizacao_falsa():
    samples = (
        walk(5)
        + [PositionSample(pt(400, 50_000), 50), PositionSample(pt(500, 0), 60)]
        + [PositionSample(pt(500, -50_000), 70), PositionSample(pt(600, 0), 80)]
    )
    result = evaluate(samples, ROUTE)
    assert result.suspected_mock_location is True
    assert result.alert is None


def test_retomada_de_sinal_em_outro_lugar_volta_a_ser_aceita():
    # Review Focus 4: depois de 3 saltos seguidos o sistema aceita a nova posição.
    samples = walk(3) + [PositionSample(pt(200, 30_000), 30 + i * 10) for i in range(4)]
    good, jumps = clean_samples(samples)
    assert jumps == 3
    assert len(good) == 5
    assert good[-1].t == 60


def test_primeira_amostra_errada_nao_trava_o_sistema():
    # Review Focus 4: a primeira amostra veio de longe; as seguintes, corretas, não podem ser jogadas fora para sempre.
    samples = [PositionSample(pt(0, 50_000), 0)] + [PositionSample(pt(0, 0), 10 * i) for i in range(1, 7)]
    good, _ = clean_samples(samples)
    assert good[-1].t == 60
    assert evaluate(samples, ROUTE).alert is None


def test_amostras_fora_de_ordem_sao_descartadas():
    good, jumps = clean_samples([PositionSample(pt(0, 0), 10), PositionSample(pt(10, 0), 5)])
    assert [s.t for s in good] == [10]
    assert jumps == 0
