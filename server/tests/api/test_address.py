"""`GET /v1/passenger/address`: o endereço escrito de um ponto, pelo Google no servidor (a chave não vai para o celular)."""
from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import GoogleMaps
from app.api.routes.passenger import ADDRESS_LOOKUPS_PER_MINUTE
from tests.api.helpers import login

RESPOSTA = {
    "status": "OK",
    "results": [
        {
            "types": ["street_address"],
            "address_components": [
                {"long_name": "120", "types": ["street_number"]},
                {"long_name": "Rua Severo Vieira", "types": ["route"]},
                {"long_name": "São Cristóvão", "types": ["sublocality_level_1", "sublocality"]},
            ],
        }
    ],
}
PARAMS = {"lat": -12.9644, "lng": -39.2597}


def test_devolve_o_endereco_escrito_do_google(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    pedidos = []

    def get(url, timeout_s):
        pedidos.append(url)
        return RESPOSTA

    runtime.maps = GoogleMaps("k", get=get)
    resposta = client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers)
    assert resposta.status_code == 200
    assert resposta.json() == {"text": "Rua Severo Vieira, 120 - São Cristóvão"}
    assert "latlng=-12.964400%2C-39.259700" in pedidos[0]


def test_sem_a_chave_do_google_responde_texto_nulo(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    runtime.maps = FakeMaps()
    resposta = client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers)
    assert resposta.status_code == 200 and resposta.json() == {"text": None}


def test_google_fora_do_ar_responde_texto_nulo_sem_erro(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")

    def cai(url, timeout_s):
        raise OSError("sem rede")

    runtime.maps = GoogleMaps("k", get=cai)
    resposta = client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers)
    assert resposta.status_code == 200 and resposta.json() == {"text": None}


def test_sem_login_e_motoqueiro_nao_entram(client, runtime):
    assert client.get("/v1/passenger/address", params=PARAMS).status_code == 401
    joao = login(client, runtime, "75 99999-0002", "rider", name="João Souza")
    assert client.get("/v1/passenger/address", params=PARAMS, headers=joao.headers).status_code == 403


def test_ponto_que_nao_existe_leva_422(client, runtime):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    for params in ({"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}, {"lat": "x", "lng": 0}, {"lat": 1}, {}):
        resposta = client.get("/v1/passenger/address", params=params, headers=ana.headers)
        assert resposta.status_code == 422, params


def test_rajada_de_consultas_leva_429_e_a_janela_seguinte_libera(client, runtime, clock):
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    bia = login(client, runtime, "75 99999-0003", "passenger", name="Bia Souza")
    runtime.maps = FakeMaps()
    for _ in range(ADDRESS_LOOKUPS_PER_MINUTE):
        assert client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers).status_code == 200
    resposta = client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers)
    assert resposta.status_code == 429 and resposta.json()["error"]["code"] == "too_many_requests"
    # o limite é de cada passageiro: a Bia não paga pela Ana
    assert client.get("/v1/passenger/address", params=PARAMS, headers=bia.headers).status_code == 200
    clock.advance(61)
    assert client.get("/v1/passenger/address", params=PARAMS, headers=ana.headers).status_code == 200
