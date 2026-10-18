import pytest

from app.infra.redis_store import (
    InMemoryJobMarks,
    InMemoryPixHealth,
    InMemoryPositionStore,
    InMemoryRateLimiter,
    RedisJobMarks,
    RedisPixHealth,
    RedisPositionStore,
    RedisRateLimiter,
)
from tests.helpers import pt


@pytest.fixture(params=["memoria", "redis"])
def limiter(request, redis_client):
    return InMemoryRateLimiter() if request.param == "memoria" else RedisRateLimiter(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def health(request, redis_client):
    return InMemoryPixHealth() if request.param == "memoria" else RedisPixHealth(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def marks(request, redis_client):
    return InMemoryJobMarks() if request.param == "memoria" else RedisJobMarks(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def positions(request, redis_client):
    return InMemoryPositionStore() if request.param == "memoria" else RedisPositionStore(redis_client)


def test_limitador_deixa_passar_ate_o_limite_e_zera_na_janela_seguinte(limiter):
    for _ in range(3):
        assert limiter.hit("pin:ride-1", 3, 600, now=1000.0) is True
    assert limiter.hit("pin:ride-1", 3, 600, now=1001.0) is False
    assert limiter.hit("pin:ride-2", 3, 600, now=1001.0) is True        # outra chave tem a sua contagem
    assert limiter.hit("pin:ride-1", 3, 600, now=1600.0) is True        # janela seguinte


def test_limitador_conta_sem_gastar_tentativa(limiter):
    assert limiter.count("pin:ride-1", 600, now=1000.0) == 0
    limiter.hit("pin:ride-1", 3, 600, now=1000.0)
    limiter.hit("pin:ride-1", 3, 600, now=1001.0)
    assert limiter.count("pin:ride-1", 600, now=1002.0) == 2
    assert limiter.count("pin:ride-1", 600, now=1002.0) == 2
    assert limiter.count("pin:ride-1", 600, now=1600.0) == 0          # janela seguinte


def test_pix_fora_do_ar_volta_sozinho_depois_do_prazo(health):
    assert health.is_down(100.0) is False
    health.mark_down(100.0, for_s=60.0)
    assert health.is_down(120.0) is True
    assert health.is_down(161.0) is False


def test_marca_de_tarefa_guarda_o_ultimo_valor(marks):
    assert marks.get("docs") is None
    marks.set("docs", "2026-10-18")
    assert marks.get("docs") == "2026-10-18"
    marks.set("docs", "2026-10-19")
    assert marks.get("docs") == "2026-10-19"


def test_limpeza_tira_so_quem_sumiu(positions):
    positions.update("velho", pt(0, 0), now=100.0)
    positions.update("novo", pt(10, 0), now=900.0)
    assert positions.prune(now=1000.0, max_age_s=300.0) == 1
    assert positions.get("velho") is None
    assert positions.get("novo") is not None
    assert positions.nearby(pt(0, 0), 1000.0, now=1000.0, max_age_s=300.0)[0][0] == "novo"
    assert positions.prune(now=1000.0, max_age_s=300.0) == 0
