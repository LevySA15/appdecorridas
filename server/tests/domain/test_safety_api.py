from app.domain.safety import PositionSample, evaluate
from tests.helpers import pt


def test_sem_rota_conhecida_so_o_aviso_de_parada_vale():
    longe = [PositionSample(pt(1000 + 100 * i, 0), 4.0 * i) for i in range(5)]
    assert evaluate(longe, []).alert is None                       # antes estourava: "a rota está vazia"
    parado = [PositionSample(pt(5, 0), 4.0 * i) for i in range(60)]
    assert evaluate(parado, []).alert is not None
