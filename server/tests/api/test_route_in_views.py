"""O traçado pelas ruas chega aos apps: na cotação, na corrida do passageiro, na oferta e na corrida do motoqueiro."""
import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import GoogleMaps
from tests.api.helpers import login, online_rider, rider_phone
from tests.api.test_rider_routes import QUOTE, aceitar, pedir

# traçado de verdade do exemplo da documentação do Google: 3 pontos que não estão em linha reta
TRACADO = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
PONTOS = [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]
RESPOSTA = {"routes": [{"distanceMeters": 2310, "duration": "412s", "polyline": {"encodedPolyline": TRACADO}}]}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


@pytest.fixture()
def google(runtime):
    runtime.maps = GoogleMaps("k", post=lambda url, headers, body, timeout_s: RESPOSTA)


def test_cotacao_leva_o_tracado_do_google(client, pax, google):
    cotacao = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    assert cotacao["route"] == PONTOS


def test_sem_google_o_tracado_e_so_embarque_e_destino(client, pax, runtime):
    runtime.maps = FakeMaps()
    cotacao = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    assert cotacao["route"] == [
        [round(QUOTE["pickup"]["lat"], 5), round(QUOTE["pickup"]["lng"], 5)],
        [round(QUOTE["destination"]["lat"], 5), round(QUOTE["destination"]["lng"], 5)],
    ]


def test_a_corrida_guarda_o_tracado_da_cotacao_dos_dois_lados_e_na_oferta(client, pax, rider, google):
    corrida = pedir(client, pax)
    assert corrida["route"] == PONTOS                                              # a resposta do pedido
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["route"] == PONTOS
    oferta = client.get("/v1/rider/state", headers=rider.headers).json()["offer"]
    assert oferta["route"] == PONTOS                                               # o motoqueiro decide vendo o trajeto
    aceita = aceitar(client, rider, corrida["ride_id"])
    assert aceita["route"] == PONTOS
    assert client.get("/v1/rider/state", headers=rider.headers).json()["ride"]["route"] == PONTOS


def test_aviso_de_oferta_em_tempo_real_leva_o_tracado(client, pax, rider, google, listen):
    avisos = listen(rider.user_id)
    pedir(client, pax)
    assert avisos.messages[0]["data"]["route"] == PONTOS


def _codifica(pontos):
    """Polilinha codificada do Google (precisão 1e5), o inverso de `decode_polyline`."""
    saida, ant_lat, ant_lng = "", 0, 0
    for la, lo in pontos:
        a, b = round(la * 1e5), round(lo * 1e5)
        for delta in (a - ant_lat, b - ant_lng):
            valor = ~(delta << 1) if delta < 0 else delta << 1
            while valor >= 0x20:
                saida += chr((0x20 | (valor & 0x1F)) + 63)
                valor >>= 5
            saida += chr(valor + 63)
        ant_lat, ant_lng = a, b
    return saida


def test_traco_comprido_do_google_chega_enxuto(client, pax, runtime):
    # 300 pontos em linha reta (a cada ~11 m) pedem só as duas pontas
    pontos = [(-12.9 - i * 0.0001, -39.26) for i in range(300)]
    resposta = {"routes": [{"distanceMeters": 3300, "duration": "400s", "polyline": {"encodedPolyline": _codifica(pontos)}}]}
    runtime.maps = GoogleMaps("k", post=lambda url, headers, body, timeout_s: resposta)
    cotacao = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    assert cotacao["route"] == [[-12.9, -39.26], [round(-12.9 - 299 * 0.0001, 5), -39.26]]


def test_a_cotacao_ja_guarda_o_traco_enxuto(client, pax, runtime, session):
    from app.db.models import QuoteRow

    pontos = [(-12.9 - i * 0.0001, -39.26) for i in range(300)]
    resposta = {"routes": [{"distanceMeters": 3300, "duration": "400s", "polyline": {"encodedPolyline": _codifica(pontos)}}]}
    runtime.maps = GoogleMaps("k", post=lambda url, headers, body, timeout_s: resposta)
    cotacao = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    linha = session.get(QuoteRow, cotacao["quote_id"])
    assert len(linha.route) == 2                               # o banco não guarda os 300 pontos
