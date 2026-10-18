import datetime as dt

import pytest

from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def pedir(client, pax, metodo="pix"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    resposta = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def aceitar(client, rider, ride_id):
    resposta = client.post(f"/v1/rider/offers/{ride_id}/accept", headers=rider.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def pagar_pix(runtime, session, ride_id):
    cobranca = repo.get_current_charge_id(session, ride_id)
    runtime.run(lambda u: u.payments.on_provider_event(u.session, runtime.provider.mark_paid(cobranca)))


def acao(client, rider, ride_id, nome, **corpo):
    return client.post(f"/v1/rider/rides/{ride_id}/{nome}", json=corpo or None, headers=rider.headers)


# --- estado e disponibilidade -----------------------------------------------------------------


def test_estado_de_quem_ainda_nao_se_cadastrou(client, runtime):
    novo = login(client, runtime, "75 99999-0002", "rider")
    estado = client.get("/v1/rider/state", headers=novo.headers).json()
    assert estado["registration"] == {"status": "not_registered"}
    assert estado["account"] is None and estado["offer"] is None and estado["ride"] is None


def test_estado_do_motoqueiro_aprovado_mostra_conta_e_nota(client, rider):
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "approved" and estado["registration"]["online"] is True
    assert estado["registration"]["rating"] is None
    assert estado["account"] == {
        "completed_rides": 0, "trial_rides": 10, "entry_paid": False, "entry_fee_cents": 5000,
        "needs_entry": False, "cash_debt_cents": 0, "cash_debt_limit_cents": 1000,
    }
    assert (estado["offer"], estado["ride"], estado["queued_ride"], estado["awaiting_payment"]) == (None,) * 4


def test_ficar_disponivel_e_parar(client, rider, session):
    assert client.post("/v1/rider/offline", headers=rider.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).online is False
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).online is True


@pytest.mark.parametrize(
    "preparar, codigo",
    [
        (lambda p, u: setattr(p, "status", "pending"), "not_approved"),
        (lambda p, u: setattr(p, "status", "blocked"), "blocked"),
        (lambda p, u: setattr(p, "cnh_expires_on", dt.date(2020, 1, 1)), "documents_expired"),
        (lambda p, u: setattr(p, "completed_rides", 10), "entry_pending"),
    ],
)
def test_nao_pode_ficar_disponivel_e_o_codigo_diz_por_que(client, rider, session, preparar, codigo):
    perfil = session.get(RiderProfileRow, rider.user_id)
    preparar(perfil, session.get(UserRow, rider.user_id))
    session.flush()
    resposta = client.post("/v1/rider/online", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == codigo


def test_cobranca_da_entrada_uma_so_e_para_quem_ainda_nao_pagou(client, rider, runtime, session):
    resposta = client.post("/v1/rider/entry-charge", headers=rider.headers)
    assert resposta.status_code == 201
    cobranca = resposta.json()
    assert cobranca["amount_cents"] == 5000 and cobranca["br_code"].startswith("fake-pix|")
    assert client.post("/v1/rider/entry-charge", headers=rider.headers).json()["charge_id"] == cobranca["charge_id"]
    runtime.run(lambda u: u.payments.on_provider_event(u.session, runtime.provider.mark_paid(cobranca["charge_id"])))
    resposta = client.post("/v1/rider/entry-charge", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"


# --- posição ----------------------------------------------------------------------------------


def test_posicao_do_motoqueiro_disponivel_vai_para_a_loja(client, rider, runtime):
    ponto = pt(500, 100)
    resposta = client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers)
    assert resposta.status_code == 204
    assert runtime.positions.get(rider.user_id).lat == pytest.approx(ponto.lat)


def test_posicao_de_quem_esta_parado_e_ignorada(client, rider, runtime):
    client.post("/v1/rider/offline", headers=rider.headers)
    runtime.positions.remove(rider.user_id)
    resposta = client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert resposta.status_code == 204 and runtime.positions.get(rider.user_id) is None


@pytest.mark.parametrize("corpo", [{"lat": 95, "lng": 0}, {"lat": 0, "lng": 200}, {"lat": "a", "lng": 0}, {}])
def test_posicao_invalida_e_422(client, rider, corpo):
    assert client.post("/v1/rider/position", json=corpo, headers=rider.headers).status_code == 422


def test_durante_a_corrida_a_posicao_chega_ao_passageiro(client, pax, rider, runtime, session, listen):
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    avisos = listen(pax.user_id)
    client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert avisos.types == ["rider_position"]
    assert avisos.messages[0]["data"] == {"ride_id": corrida["ride_id"], "lat": ORIGIN.lat, "lng": ORIGIN.lng}


def test_sem_corrida_a_posicao_nao_vai_para_ninguem(client, pax, rider, listen):
    avisos = listen(pax.user_id)
    client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert avisos.messages == []


# --- ofertas ----------------------------------------------------------------------------------


def test_oferta_aparece_no_estado_igual_ao_aviso(client, pax, rider, listen):
    avisos = listen(rider.user_id)
    corrida = pedir(client, pax)
    oferta = client.get("/v1/rider/state", headers=rider.headers).json()["offer"]
    assert oferta == avisos.messages[0]["data"]
    assert oferta["ride_id"] == corrida["ride_id"] and oferta["payment_method"] == "pix"
    assert oferta["will_queue"] is False and oferta["seconds_to_pickup"] > 0


def test_aceitar_mostra_a_corrida_do_lado_do_motoqueiro_e_avisa_o_passageiro(client, pax, rider, listen):
    avisos = listen(pax.user_id)
    corrida = pedir(client, pax)
    ride = aceitar(client, rider, corrida["ride_id"])
    assert ride["state"] == "accepted" and ride["passenger"] == {"name": "Ana"} and ride["fee_cents"] == 100
    assert "pin" not in ride and ride["pix_paid"] is False and ride["method"] == "pix"
    assert ride["pickup"]["text"] == "Rua A" and ride["destination"]["text"] == "Feira livre"
    aviso = next(m for m in avisos.messages if m["type"] == "rider_accepted")["data"]
    assert aviso["pin"] == corrida["pin"] and aviso["pay"]["amount_cents"] == corrida["price_cents"]
    assert client.get("/v1/rider/state", headers=rider.headers).json()["ride"]["ride_id"] == corrida["ride_id"]


def test_recusar_passa_a_oferta_adiante_sem_penalidade(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/decline", headers=rider.headers).status_code == 204
    assert client.get("/v1/rider/state", headers=rider.headers).json()["offer"] is None
    assert client.get("/v1/rider/state", headers=outro.headers).json()["offer"]["ride_id"] == corrida["ride_id"]


def test_oferta_que_nao_e_sua_ou_que_venceu(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=outro.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "offer_gone"
    clock.advance(16)
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "offer_gone"
    assert client.post("/v1/rider/offers/nao-existe/decline", headers=rider.headers).status_code == 404
    assert client.post("/v1/rider/offers/nao-existe/accept", headers=rider.headers).status_code == 404


# --- andamento ------------------------------------------------------------------------------------


def test_corrida_pix_do_aceite_ao_fim_com_avisos_ao_passageiro(client, pax, rider, runtime, session, listen):
    avisos = listen(pax.user_id)
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    rid = corrida["ride_id"]

    assert acao(client, rider, rid, "arrive").status_code == 200
    assert acao(client, rider, rid, "helmet").status_code == 200
    resposta = acao(client, rider, rid, "start", pin=corrida["pin"])
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"      # Pix não pago
    pagar_pix(runtime, session, rid)
    errado = "0000" if corrida["pin"] != "0000" else "1111"
    resposta = acao(client, rider, rid, "start", pin=errado)
    assert resposta.status_code == 422 and resposta.json()["error"]["code"] == "wrong_pin"
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).json()["state"] == "in_progress"
    final = acao(client, rider, rid, "complete").json()
    assert final["state"] == "completed" and final["end_payment"] is None
    assert {"rider_accepted", "rider_arrived", "trip_started", "trip_completed"} <= set(avisos.types)

    assert client.post(f"/v1/rides/{rid}/rating", json={"stars": 5}, headers=rider.headers).status_code == 204
    assert client.get("/v1/rider/state", headers=rider.headers).json()["account"]["completed_rides"] == 1


def test_corrida_em_dinheiro_termina_com_qr_e_motoqueiro_confirma(client, pax, rider, runtime, session):
    corrida = pedir(client, pax, "cash")
    rid = corrida["ride_id"]
    aceitar(client, rider, rid)
    acao(client, rider, rid, "arrive")
    acao(client, rider, rid, "helmet")
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).status_code == 200
    final = acao(client, rider, rid, "complete").json()
    assert final["end_payment"]["amount_cents"] == corrida["price_cents"] and final["end_payment"]["blocked"] is False
    assert final["end_payment"]["charge_id"] == repo.get_current_charge_id(session, rid)
    espera = client.get("/v1/rider/state", headers=rider.headers).json()["awaiting_payment"]
    assert espera["ride_id"] == rid

    assert acao(client, rider, rid, "cash-received").status_code == 204
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["awaiting_payment"] is None and estado["account"]["cash_debt_cents"] == 100


def test_codigo_errado_demais_trava_a_corrida_por_dez_minutos(client, pax, rider, clock, runtime, session):
    corrida = pedir(client, pax)
    rid = corrida["ride_id"]
    aceitar(client, rider, rid)
    acao(client, rider, rid, "arrive")
    acao(client, rider, rid, "helmet")
    pagar_pix(runtime, session, rid)
    errado = "0000" if corrida["pin"] != "0000" else "1111"
    for _ in range(5):
        assert acao(client, rider, rid, "start", pin=errado).status_code == 422
    resposta = acao(client, rider, rid, "start", pin=corrida["pin"])
    assert resposta.status_code == 429 and resposta.json()["error"]["code"] == "too_many_requests"
    clock.advance(601)
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).status_code == 200


@pytest.mark.parametrize("pin", ["12", "12345", "abcd", ""])
def test_codigo_com_formato_ruim_e_422(client, pax, rider, pin):
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    assert acao(client, rider, corrida["ride_id"], "start", pin=pin).status_code == 422


def test_so_o_motoqueiro_da_corrida_mexe_nela(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    for nome in ("arrive", "helmet", "complete", "cash-received"):
        resposta = acao(client, outro, corrida["ride_id"], nome)
        assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "not_your_ride", nome
    assert acao(client, rider, "nao-existe", "arrive").status_code == 404


def test_rotas_do_motoqueiro_sao_so_do_motoqueiro(client, pax):
    for metodo, url in (
        ("get", "/v1/rider/state"), ("post", "/v1/rider/online"), ("post", "/v1/rider/offline"),
        ("post", "/v1/rider/position"), ("post", "/v1/rider/entry-charge"), ("post", "/v1/rider/offers/x/accept"),
        ("post", "/v1/rider/rides/x/arrive"),
    ):
        assert getattr(client, metodo)(url, headers=pax.headers).status_code == 403, url
        assert getattr(client, metodo)(url).status_code == 401, url
