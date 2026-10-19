import pytest

from app.db import repositories as repo
from app.db.models import QuoteRow, RiderProfileRow
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


def cotar(client, quem, corpo=QUOTE):
    resposta = client.post("/v1/passenger/quotes", json=corpo, headers=quem.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def pedir(client, quem, quote_id, metodo="pix"):
    return client.post("/v1/passenger/rides", json={"quote_id": quote_id, "method": metodo}, headers=quem.headers)


# --- preço -----------------------------------------------------------------------------------


def test_cotacao_mostra_preco_motivo_chegada_e_formas_de_pagar(client, pax, session, runtime, clock):
    online_rider(session, runtime, clock)
    corpo = cotar(client, pax)
    assert corpo["price_cents"] == 550 and corpo["reason"] == "Muita moto livre agora, preço menor."   # 1 moto, 0 pedidos
    assert corpo["payment_methods"] == ["pix", "cash"]
    assert corpo["nearby_riders"] == 1 and 40 <= corpo["eta_seconds"] <= 70
    assert corpo["pickup"] == lugar(ORIGIN, "Rua A") | {"lat": ORIGIN.lat, "lng": ORIGIN.lng}
    assert corpo["expires_at"] == clock.now + 300
    assert session.get(QuoteRow, corpo["quote_id"]).passenger_id == pax.user_id


def test_sem_motos_a_cotacao_sai_sem_tempo_de_chegada(client, pax):
    corpo = cotar(client, pax)
    assert corpo["eta_seconds"] is None and corpo["nearby_riders"] == 0


@pytest.mark.parametrize(
    "mudar, status",
    [
        ({"pickup": lugar(ORIGIN, "A") | {"lat": 91}}, 422),
        ({"destination": lugar(ORIGIN, "A") | {"lng": -181}}, 422),
        ({"destination": lugar(ORIGIN, "A") | {"lat": "norte"}}, 422),
        ({"pickup": lugar(ORIGIN, "x" * 201)}, 422),
        ({"destination": lugar(ORIGIN, "mesmo lugar")}, 403),
        ({"destination": lugar(pt(80_000, 0), "outra cidade")}, 403),
    ],
)
def test_cotacao_com_lugar_invalido_ou_trajeto_absurdo_e_recusada(client, pax, mudar, status):
    resposta = client.post("/v1/passenger/quotes", json=QUOTE | mudar, headers=pax.headers)
    assert resposta.status_code == status


def test_pix_fora_do_ar_oferece_so_dinheiro_e_recusa_pedido_em_pix(client, pax, runtime, clock):
    runtime.pix_health.mark_down(clock.now, for_s=60)
    corpo = cotar(client, pax)
    assert corpo["payment_methods"] == ["cash"]
    resposta = pedir(client, pax, corpo["quote_id"], "pix")
    assert resposta.status_code == 403 and "Pix" in resposta.json()["error"]["message"]
    assert pedir(client, pax, corpo["quote_id"], "cash").status_code == 201      # a cotação não foi gasta
    clock.advance(61)
    assert cotar(client, login(client, runtime, "75 99999-0007", "passenger"))["payment_methods"] == ["pix", "cash"]


# --- pedido ----------------------------------------------------------------------------------


def test_pedido_procura_moto_e_so_depois_do_commit_o_motoqueiro_recebe_a_oferta(
    client, pax, session, runtime, clock, listen
):
    rider_id = online_rider(session, runtime, clock)
    avisos = listen(rider_id)
    resposta = pedir(client, pax, cotar(client, pax)["quote_id"])
    assert resposta.status_code == 201
    corrida = resposta.json()
    assert corrida["state"] == "searching" and corrida["method"] == "pix" and corrida["price_cents"] == 550
    assert len(corrida["pin"]) == 4 and corrida["rider"] is None and corrida["pay"] is None
    assert corrida["pickup"]["text"] == "Rua A" and corrida["destination"]["text"] == "Feira livre"
    assert avisos.types == ["offer"]
    assert avisos.messages[0]["data"]["ride_id"] == corrida["ride_id"]
    assert avisos.messages[0]["data"]["price_cents"] == 550


def test_pedido_sem_moto_fica_procurando(client, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"], "cash").json()
    assert corrida["state"] == "searching" and corrida["method"] == "cash"


def test_so_uma_corrida_por_vez_e_cotacao_de_outro_nao_vale(client, runtime, pax):
    primeira, segunda = cotar(client, pax), cotar(client, pax)
    assert pedir(client, pax, primeira["quote_id"]).status_code == 201
    resposta = pedir(client, pax, segunda["quote_id"])
    assert resposta.status_code == 403 and "já tem uma corrida" in resposta.json()["error"]["message"]
    outro = login(client, runtime, "75 99999-0005", "passenger")
    resposta = pedir(client, outro, primeira["quote_id"])
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "quote_expired"
    assert pedir(client, pax, "q-inventada").status_code == 409


def test_forma_de_pagar_invalida_e_422(client, pax):
    resposta = client.post("/v1/passenger/rides", json={"quote_id": "q-1", "method": "cartao"}, headers=pax.headers)
    assert resposta.status_code == 422


def test_cancelar_retira_a_oferta_do_motoqueiro_e_libera_o_passageiro(client, pax, session, runtime, clock, listen):
    rider_id = online_rider(session, runtime, clock)
    avisos = listen(rider_id)
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    resposta = client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers)
    assert resposta.status_code == 200
    assert resposta.json() == {"refund": False, "fee_cents": 0, "fee": None, "refund_to": None, "balance_cents": 0}
    assert avisos.types == ["offer", "offer_expired"]
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None
    assert pedir(client, pax, cotar(client, pax)["quote_id"]).status_code == 201


def test_cancelar_corrida_dos_outros_ou_inexistente(client, runtime, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    outro = login(client, runtime, "75 99999-0005", "passenger")
    resposta = client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=outro.headers)
    assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "not_your_ride"
    assert client.post("/v1/passenger/rides/nao-existe/cancel", headers=pax.headers).status_code == 404


# --- estado (o que o app pede ao abrir ou reconectar) --------------------------------------------


def test_estado_do_passageiro_sem_corrida(client, pax):
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado == {
        "ride": None, "pending_payment": None, "blocked_reason": None, "unpaid_cents": 0,
        "emergency_contact": None, "payment_methods": ["pix", "cash"],
        "balance_cents": 0, "topup_enabled": False, "pending_fee": None, "recent_fees": [],
    }


def test_estado_com_motoqueiro_a_caminho_traz_ficha_codigo_pix_e_posicao(
    client, pax, session, runtime, clock
):
    rider_id = online_rider(session, runtime, clock)
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    runtime.run(lambda u: u.dispatch.accept_offer(u.session, rider_id, corrida["ride_id"], u.now))
    ride = client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]
    assert ride["state"] == "accepted" and ride["pin"] == corrida["pin"] and ride["queued"] is False
    assert ride["rider"]["name"] == f"Motoqueiro {rider_id}" and ride["rider"]["plate"] == "ABC0001"
    assert ride["rider"]["photo_url"] is None and ride["rider"]["rating"] is None
    assert ride["pay"]["amount_cents"] == 550 and ride["pay"]["expires_at"] == clock.now + 120
    assert ride["pay"]["charge_id"] == repo.get_current_charge_id(session, corrida["ride_id"])
    assert ride["rider_position"] == pytest.approx({"lat": pt(300, 0).lat, "lng": pt(300, 0).lng}, abs=1e-5)


def test_estado_mostra_pagamento_pendente_e_bloqueio_de_quem_nao_pagou(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.CASH, price=700, fee=100)
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado["pending_payment"] == {
        "ride_id": "ride-9", "amount_cents": 700, "charge_id": None, "blocked": False,
    }
    assert estado["blocked_reason"] and "Falta pagar" in estado["blocked_reason"]


# --- contato de emergência ------------------------------------------------------------------------


def test_contato_de_emergencia_guarda_o_numero_normalizado(client, pax):
    corpo = {"name": "Maria", "phone": "(75) 98888-7777"}
    assert client.put("/v1/passenger/emergency-contact", json=corpo, headers=pax.headers).status_code == 204
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado["emergency_contact"] == {"name": "Maria", "phone": "+5575988887777"}


@pytest.mark.parametrize(
    "corpo",
    [{"name": "Eu mesmo", "phone": "75 99999-0001"}, {"name": "Maria", "phone": "123"}, {"name": "", "phone": "75 98888-7777"}],
)
def test_contato_de_emergencia_invalido_e_recusado(client, pax, corpo):
    assert client.put("/v1/passenger/emergency-contact", json=corpo, headers=pax.headers).status_code == 422


# --- avaliação ----------------------------------------------------------------------------------------


def test_avaliar_o_motoqueiro_uma_vez_so_e_atualiza_a_nota(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX)
    resposta = client.post("/v1/rides/ride-9/rating", json={"stars": 5}, headers=pax.headers)
    assert resposta.status_code == 204
    assert session.get(RiderProfileRow, rider_id).rating_count == 1
    segunda = client.post("/v1/rides/ride-9/rating", json={"stars": 1}, headers=pax.headers)
    assert segunda.status_code == 409 and segunda.json()["error"]["code"] == "already_rated"


@pytest.mark.parametrize("estrelas", [0, 6, -1, "cinco", None])
def test_nota_fora_de_1_a_5_e_422(client, pax, estrelas):
    assert client.post("/v1/rides/ride-9/rating", json={"stars": estrelas}, headers=pax.headers).status_code == 422


def test_so_quem_participou_avalia_e_so_corrida_terminada(client, runtime, pax, session, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX)
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    resposta = client.post("/v1/rides/ride-9/rating", json={"stars": 5}, headers=intruso.headers)
    assert resposta.status_code == 403
    assert client.post("/v1/rides/nao-existe/rating", json={"stars": 5}, headers=pax.headers).status_code == 404
    aberta = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    resposta = client.post(f"/v1/rides/{aberta['ride_id']}/rating", json={"stars": 5}, headers=pax.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"


def test_rotas_do_passageiro_sao_so_do_passageiro(client, runtime):
    motoqueiro = login(client, runtime, "75 99999-0002", "rider")
    for metodo, url in (
        ("post", "/v1/passenger/quotes"), ("post", "/v1/passenger/rides"), ("get", "/v1/passenger/state"),
        ("put", "/v1/passenger/emergency-contact"),
    ):
        assert getattr(client, metodo)(url, headers=motoqueiro.headers).status_code == 403
        assert getattr(client, metodo)(url).status_code == 401


def test_passageiro_na_fila_ve_onde_a_moto_termina_e_quanto_falta(client, pax, session, runtime, clock):
    from app.db.models import RiderProfileRow
    from tests.helpers_db import add_accepted_ride, add_passenger

    rider_id = online_rider(session, runtime, clock, 1, pt(100, 0))
    add_passenger(session, "p0", "+5575900000010")
    add_accepted_ride(session, ride_id="ride-0", passenger_id="p0", rider_id=rider_id)
    repo.set_ride_details(
        session, "ride-0", repo.RideDetails(pt(-2000, 0), pt(300, 0), "Origem", "Mercado", 2300, 1.0, "")
    )
    session.get(RiderProfileRow, rider_id).online = True
    session.flush()
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    runtime.run(lambda u: u.dispatch.accept_offer(u.session, rider_id, corrida["ride_id"], u.now))
    ride = client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]
    assert ride["state"] == "queued" and ride["queued"] is True
    assert ride["queue"]["finishing_at"] == "Mercado" and ride["queue"]["eta_seconds"] > 0
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["rider_position"] is None
