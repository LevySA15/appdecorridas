"""Histórico de corridas do passageiro: só as encerradas, da mais nova para a mais antiga, com o recibo de cada uma."""
import pytest

from app.db.models import RideRow
from app.domain.types import PaymentMethod
from tests.api.helpers import login, online_rider
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_completed_ride


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


def pedir(client, quem, quote_id, metodo="pix"):
    return client.post("/v1/passenger/rides", json={"quote_id": quote_id, "method": metodo}, headers=quem.headers)


def historico(client, quem, **params):
    return client.get("/v1/passenger/rides", params=params, headers=quem.headers)


def test_sem_corridas_o_historico_vem_vazio(client, pax):
    assert historico(client, pax).json() == {"rides": [], "has_more": False}


def test_corrida_concluida_traz_recibo_completo(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX, price=550)
    assert client.post("/v1/rides/ride-9/rating", json={"stars": 4}, headers=pax.headers).status_code == 204
    item = historico(client, pax).json()["rides"][0]
    assert item["ride_id"] == "ride-9" and item["state"] == "completed" and item["price_cents"] == 550
    assert item["method"] == "pix" and item["my_stars"] == 4 and item["fee_cents"] == 0
    assert item["fee_refunded"] is False and item["payment_pending"] is False
    assert item["rider"]["name"] == f"Motoqueiro {rider_id}" and item["rider"]["plate"] == "ABC0001"
    assert set(item["rider"]) == {"name", "plate", "moto_model"}
    assert isinstance(item["created_at"], float)


def test_corrida_cancelada_sem_motoqueiro_nao_tem_ficha(client, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    assert client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers).status_code == 200
    item = historico(client, pax).json()["rides"][0]
    assert item["state"] == "cancelled" and item["rider"] is None and item["my_stars"] is None
    assert item["pickup_text"] == "Rua A" and item["destination_text"] == "Feira livre"
    assert item["fee_cents"] == 0 and item["distance_m"] > 0


def test_corrida_aberta_e_corrida_dos_outros_nao_entram(client, runtime, pax, session, clock):
    pedir(client, pax, cotar(client, pax)["quote_id"])                       # aberta
    rider_id = online_rider(session, runtime, clock)
    outra = login(client, runtime, "75 99999-0005", "passenger")
    add_completed_ride(session, "ride-7", outra.user_id, rider_id, PaymentMethod.PIX)
    assert historico(client, pax).json()["rides"] == []


def test_dinheiro_nao_pago_e_pagamento_com_saldo(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-1", pax.user_id, rider_id, PaymentMethod.CASH)
    add_completed_ride(session, "ride-2", pax.user_id, rider_id, PaymentMethod.PIX)
    session.get(RideRow, "ride-2").pay_with_balance = True
    session.flush()
    por_id = {i["ride_id"]: i for i in historico(client, pax).json()["rides"]}
    assert por_id["ride-1"]["payment_pending"] is True and por_id["ride-1"]["method"] == "cash"
    assert por_id["ride-2"]["method"] == "balance" and por_id["ride-2"]["payment_pending"] is False


def test_paginacao_mais_nova_primeiro_e_has_more(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    for n in (1, 2, 3):
        add_completed_ride(session, f"ride-{n}", pax.user_id, rider_id, PaymentMethod.PIX)
    primeira = historico(client, pax, limit=2).json()
    assert [i["ride_id"] for i in primeira["rides"]] == ["ride-3", "ride-2"] and primeira["has_more"] is True
    segunda = historico(client, pax, limit=2, offset=2).json()
    assert [i["ride_id"] for i in segunda["rides"]] == ["ride-1"] and segunda["has_more"] is False


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"limit": "x"}])
def test_limite_e_deslocamento_invalidos_sao_422(client, pax, params):
    assert historico(client, pax, **params).status_code == 422
