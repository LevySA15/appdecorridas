"""Cotar e pedir corrida em rajada leva 429 (protege o mapa pago e a fila dos motoqueiros); passageiro normal nem sente."""
from app.api.routes.passenger import QUOTES_PER_MINUTE, RIDE_REQUESTS_PER_MINUTE
from tests.api.helpers import login
from tests.api.test_rider_routes import QUOTE


def test_rajada_de_cotacoes_leva_429_e_a_janela_seguinte_libera(client, runtime, clock):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    bia = login(client, runtime, "75 99999-0002", "passenger", name="Bia Souza")
    for _ in range(QUOTES_PER_MINUTE):
        assert client.post("/v1/passenger/quotes", json=QUOTE, headers=ana.headers).status_code == 200
    resposta = client.post("/v1/passenger/quotes", json=QUOTE, headers=ana.headers)
    assert resposta.status_code == 429
    assert resposta.json()["error"]["code"] == "too_many_requests"
    # o limite é de cada passageiro: a Bia não paga pela Ana
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=bia.headers).status_code == 200
    clock.advance(61)
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=ana.headers).status_code == 200


def test_rajada_de_pedidos_leva_429(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    for _ in range(RIDE_REQUESTS_PER_MINUTE):
        # quote inexistente: o pedido falha, mas conta como tentativa
        assert client.post("/v1/passenger/rides", json={"quote_id": "nao-existe", "method": "cash"}, headers=ana.headers).status_code != 429
    assert client.post("/v1/passenger/rides", json={"quote_id": "nao-existe", "method": "cash"}, headers=ana.headers).status_code == 429


def test_passageiro_normal_nao_sente_o_limite(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    for _ in range(5):
        assert client.post("/v1/passenger/quotes", json=QUOTE, headers=ana.headers).status_code == 200
