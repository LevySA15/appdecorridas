import redis
import pytest

from app.infra.redis_store import RedisPositionStore, RedisReservationBook


def test_cliente_de_teste_usa_o_banco_15_mesmo_com_url_de_outro_banco(redis_client):
    # Review final: `from_url(url, db=15)` perde para o número do banco que já vem na URL (.../0).
    assert redis_client.connection_pool.connection_kwargs["db"] == 15


def test_posicoes_recusam_cliente_sem_decode_responses():
    # Review final: sem decode_responses os ids voltam como bytes e não batem com os do banco.
    with pytest.raises(ValueError, match="decode_responses"):
        RedisPositionStore(redis.Redis())


def test_reserva_funciona_tambem_com_cliente_sem_decode_responses(redis_test_url):
    cru = redis.Redis.from_url(redis_test_url)
    try:
        cru.flushdb()
        book = RedisReservationBook(cru, ttl_ms=30_000)
        assert book.reserve("rider-1", "ride-1") is True
        assert book.reserve("rider-1", "ride-1") is True  # a mesma corrida renova
        assert book.reserve("rider-1", "ride-2") is False
    finally:
        cru.flushdb()
        cru.close()


class _ClienteComDisputa:
    """Simula a reserva vencer e outra corrida pegar a moto logo depois de um GET."""

    def __init__(self, real, chave, outra_corrida):
        self._real, self._chave, self._outra = real, chave, outra_corrida

    def get(self, *args, **kwargs):
        valor = self._real.get(*args, **kwargs)
        self._real.set(self._chave, self._outra)
        return valor

    def __getattr__(self, nome):
        return getattr(self._real, nome)


def test_renovar_reserva_nunca_diz_sim_para_quem_perdeu_a_moto(redis_client):
    # Review final: GET e PEXPIRE separados deixavam a corrida A renovar a reserva da corrida B.
    assert RedisReservationBook(redis_client, ttl_ms=30_000).reserve("rider-1", "ride-A") is True
    disputado = RedisReservationBook(
        _ClienteComDisputa(redis_client, "resv:rider-1", "ride-B"), ttl_ms=30_000
    )
    resultado = disputado.reserve("rider-1", "ride-A")
    dono = redis_client.get("resv:rider-1")
    assert resultado is (dono == "ride-A")
