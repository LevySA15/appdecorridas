from app.infra.redis_store import InMemoryFactorStore, RedisFactorStore


def test_fator_em_memoria():
    store = InMemoryFactorStore()
    assert store.get() is None
    store.set(1.1, 500.0)
    assert store.get() == (1.1, 500.0)


def test_fator_no_redis_sobrevive_ao_cliente(redis_client):
    store = RedisFactorStore(redis_client)
    assert store.get() is None
    store.set(0.9, 700.0)
    assert RedisFactorStore(redis_client).get() == (0.9, 700.0)
