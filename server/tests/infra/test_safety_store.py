import pytest

from app.domain.geo import GeoPoint
from app.domain.safety import PositionSample
from app.infra.safety_store import InMemorySafetyStore, RedisSafetyStore
from tests.helpers import pt


@pytest.fixture(params=["memoria", "redis"])
def store(request, redis_client):
    return InMemorySafetyStore() if request.param == "memoria" else RedisSafetyStore(redis_client)


def test_guarda_as_posicoes_na_ordem_e_so_as_ultimas(store):
    for i in range(5):
        amostras = store.add_sample("ride-1", PositionSample(pt(10 * i, 0), 100.0 + i), max_samples=3)
    assert [a.t for a in amostras] == [102.0, 103.0, 104.0]
    assert amostras[-1].point.lat == pytest.approx(pt(40, 0).lat)
    assert [a.t for a in store.add_sample("ride-2", PositionSample(pt(0, 0), 1.0), max_samples=3)] == [1.0]


def test_rota_nunca_vista_e_none_e_rota_vazia_tambem_e_lembrada(store):
    assert store.get_route("ride-1") is None
    store.set_route("ride-1", [])
    assert store.get_route("ride-1") == []
    store.set_route("ride-2", [GeoPoint(-12.96, -39.26), GeoPoint(-12.95, -39.25)])
    assert store.get_route("ride-2") == [GeoPoint(-12.96, -39.26), GeoPoint(-12.95, -39.25)]


def test_aviso_so_sai_uma_vez_por_periodo(store):
    assert store.claim("ride-1:stopped", now=1000.0, cooldown_s=600.0) is True
    assert store.claim("ride-1:stopped", now=1100.0, cooldown_s=600.0) is False
    assert store.claim("ride-1:off_route", now=1100.0, cooldown_s=600.0) is True       # outro tipo, outra conta
    assert store.claim("ride-1:stopped", now=1601.0, cooldown_s=600.0) is True         # passou o prazo
