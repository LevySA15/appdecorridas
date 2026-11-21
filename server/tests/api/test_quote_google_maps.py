"""A cotação pela API com o mapa do Google: a rota dele vira distância, tempo e traçado; se ele falha, a cotação sai igual."""
import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import GoogleMaps
from tests.api.helpers import login
from tests.helpers import ORIGIN, pt

TRACADO = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
RESPOSTA = {"routes": [{"distanceMeters": 2310, "duration": "412s", "polyline": {"encodedPolyline": TRACADO}}]}


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


def cotar(client, quem):
    resposta = client.post("/v1/passenger/quotes", json=QUOTE, headers=quem.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_cotacao_usa_distancia_e_tempo_do_google(client, runtime, pax):
    runtime.maps = GoogleMaps("k", post=lambda url, headers, body, timeout_s: RESPOSTA)
    cotacao = cotar(client, pax)
    assert cotacao["distance_m"] == 2310 and cotacao["duration_s"] == 412


def test_google_fora_do_ar_a_cotacao_sai_pela_estimativa(client, runtime, pax):
    def cai(url, headers, body, timeout_s):
        raise OSError("sem rede")

    runtime.maps = GoogleMaps("k", post=cai)
    cotacao = cotar(client, pax)
    esperado = FakeMaps().route(ORIGIN, pt(1500, 0))
    assert cotacao["distance_m"] == esperado.distance_m and cotacao["duration_s"] == esperado.duration_s
