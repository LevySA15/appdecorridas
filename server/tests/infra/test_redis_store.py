import threading
import time

import pytest

from app.domain.dispatch import ReservationBook
from app.infra.redis_store import InMemoryPositionStore, RedisPositionStore, RedisReservationBook
from tests.helpers import ORIGIN, pt


@pytest.fixture(params=["memoria", "redis"])
def store(request, redis_client):
    if request.param == "memoria":
        return InMemoryPositionStore()
    return RedisPositionStore(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def book(request, redis_client):
    if request.param == "memoria":
        return ReservationBook()
    return RedisReservationBook(redis_client, ttl_ms=30_000)


def test_guarda_e_devolve_a_posicao(store):
    store.update("r1", pt(100, 50), now=100)
    got = store.get("r1")
    assert got.lat == pytest.approx(pt(100, 50).lat, abs=1e-5)
    assert got.lng == pytest.approx(pt(100, 50).lng, abs=1e-5)


def test_posicao_desconhecida_e_none(store):
    assert store.get("ninguem") is None


def test_busca_por_perto_ordena_pela_distancia(store):
    store.update("longe", pt(5000, 0), now=100)
    store.update("r2", pt(300, 0), now=100)
    store.update("r1", pt(100, 0), now=100)
    result = store.nearby(ORIGIN, radius_m=1000, now=100)
    assert [rider_id for rider_id, _ in result] == ["r1", "r2"]


def test_posicao_antiga_nao_conta(store):
    store.update("r1", pt(100, 0), now=100)
    assert store.nearby(ORIGIN, 1000, now=120, max_age_s=30) != []
    assert store.nearby(ORIGIN, 1000, now=200, max_age_s=30) == []


def test_remover_tira_da_busca(store):
    store.update("r1", pt(100, 0), now=100)
    store.remove("r1")
    assert store.get("r1") is None
    assert store.nearby(ORIGIN, 1000, now=100) == []


def test_atualizar_move_a_moto(store):
    store.update("r1", pt(100, 0), now=100)
    store.update("r1", pt(5000, 0), now=110)
    assert store.nearby(ORIGIN, 1000, now=110) == []


def test_reserva_e_idempotente_para_a_mesma_corrida_e_recusa_outra(book):
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-2")  # corrida errada: não libera
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-1")
    assert book.reserve("rider-1", "ride-2") is True


def test_reserva_com_pedidos_ao_mesmo_tempo_so_um_ganha(book):
    results: list[bool] = []
    lock = threading.Lock()

    def tentar(ride_id: str) -> None:
        ok = book.reserve("rider-1", ride_id)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=tentar, args=(f"ride-{i}",)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 1


def test_reserva_do_redis_expira_sozinha(redis_client):
    # Review Focus 5: se ninguém liberar a reserva, a moto não fica presa para sempre.
    book = RedisReservationBook(redis_client, ttl_ms=150)
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    time.sleep(0.3)
    assert book.reserve("rider-1", "ride-2") is True
