import pytest

from app.db import repositories as repo
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


@pytest.fixture()
def admin(client, runtime, session):
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    return login(client, runtime, "75 99999-0000", "admin")


def corrida(client, pax, rider, ate="start"):
    """Corrida em dinheiro levada até `ate`: accept, arrive, start."""
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    pedido = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
    ).json()
    rid = pedido["ride_id"]
    assert client.post(f"/v1/rider/offers/{rid}/accept", headers=rider.headers).status_code == 200
    if ate == "accept":
        return pedido
    client.post(f"/v1/rider/rides/{rid}/arrive", headers=rider.headers)
    client.post(f"/v1/rider/rides/{rid}/helmet", headers=rider.headers)
    assert client.post(f"/v1/rider/rides/{rid}/start", json={"pin": pedido["pin"]}, headers=rider.headers).status_code == 200
    return pedido


def posicao(client, rider, ponto):
    assert client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers).status_code == 204


def parar_por(client, rider, clock, segundos, ponto=None):
    for _ in range(segundos // 4):
        clock.advance(4)
        posicao(client, rider, ponto or pt(500, 3))


def test_moto_parada_na_corrida_pergunta_ao_passageiro_e_ele_responde(client, pax, rider, admin, clock, listen):
    pedido = corrida(client, pax, rider)
    avisos_pax, avisos_admin = listen(pax.user_id), listen(admin.user_id)
    parar_por(client, rider, clock, 200)
    assert avisos_pax.types.count("safety_check") == 1
    pergunta = next(m for m in avisos_pax.messages if m["type"] == "safety_check")["data"]
    assert pergunta["ride_id"] == pedido["ride_id"] and pergunta["kind"] == "stopped"
    assert avisos_admin.types == ["safety_alert"]

    rota = f"/v1/rides/{pedido['ride_id']}/safety/{pergunta['alert_id']}/ok"
    assert client.post(rota, headers=pax.headers).status_code == 204
    repetida = client.post(rota, headers=pax.headers)
    assert repetida.status_code == 409 and repetida.json()["error"]["code"] == "alert_closed"
    assert avisos_admin.types == ["safety_alert", "safety_ok"]


def test_corrida_ainda_nao_iniciada_nao_gera_aviso_automatico(client, pax, rider, clock, listen):
    corrida(client, pax, rider, ate="accept")
    avisos = listen(pax.user_id)
    parar_por(client, rider, clock, 300)
    assert "safety_check" not in avisos.types and avisos.types.count("rider_position") == 75


def test_so_o_passageiro_da_corrida_responde_o_aviso(client, runtime, pax, rider, clock, listen):
    pedido = corrida(client, pax, rider)
    avisos = listen(pax.user_id)
    parar_por(client, rider, clock, 200)
    alerta = next(m for m in avisos.messages if m["type"] == "safety_check")["data"]["alert_id"]
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    rota = f"/v1/rides/{pedido['ride_id']}/safety/{alerta}/ok"
    assert client.post(rota, headers=intruso.headers).status_code == 403
    assert client.post(rota, headers=rider.headers).status_code == 403
    assert client.post(rota).status_code == 401
    assert client.post(f"/v1/rides/{pedido['ride_id']}/safety/999999/ok", headers=pax.headers).status_code == 404


def test_sos_avisa_o_contato_e_os_administradores_e_aparece_na_lista(client, runtime, pax, rider, admin, listen):
    client.put("/v1/passenger/emergency-contact", json={"name": "Maria", "phone": "75 98888-7777"}, headers=pax.headers)
    pedido = corrida(client, pax, rider)
    posicao(client, rider, pt(700, 20))
    avisos_pax, avisos_admin = listen(pax.user_id), listen(admin.user_id)

    resposta = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo == {
        "alert_id": corpo["alert_id"], "contact_registered": True, "contact_notified": True,
        "repeated": False, "emergency_number": "190",
    }
    [(telefone, texto)] = runtime.notifier.sent
    assert telefone == "+5575988887777" and "Ana Lima" in texto and "ABC0001" in texto
    assert avisos_pax.types == ["sos_sent"] and avisos_admin.types == ["sos"]

    lista = client.get("/v1/admin/safety-alerts", params={"status": "sos"}, headers=admin.headers).json()
    assert [(a["alert_id"], a["kind"], a["passenger_name"], a["plate"]) for a in lista] == [
        (corpo["alert_id"], "sos", "Ana Lima", "ABC0001")
    ]
    assert lista[0]["lat"] == pytest.approx(pt(700, 20).lat, abs=1e-5)
    assert client.get("/v1/admin/safety-alerts", headers=admin.headers).json() == []         # "open" está vazio

    assert client.post(
        f"/v1/admin/safety-alerts/{corpo['alert_id']}/resolve", json={"note": "Liguei, tudo bem."}, headers=admin.headers
    ).status_code == 204
    resolvidos = client.get("/v1/admin/safety-alerts", params={"status": "resolved"}, headers=admin.headers).json()
    assert resolvidos[0]["note"] == "Liguei, tudo bem."
    again = client.post(f"/v1/admin/safety-alerts/{corpo['alert_id']}/resolve", json={}, headers=admin.headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "alert_closed"


def test_sos_funciona_a_caminho_mesmo_sem_contato_e_nao_repete(client, runtime, pax, rider):
    pedido = corrida(client, pax, rider, ate="accept")
    primeiro = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers).json()
    assert (primeiro["contact_registered"], primeiro["contact_notified"], primeiro["repeated"]) == (False, False, False)
    segundo = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers).json()
    assert segundo["repeated"] is True and segundo["alert_id"] == primeiro["alert_id"]
    assert runtime.notifier.sent == []


def test_sos_fora_da_corrida_ou_de_outra_pessoa(client, runtime, pax, rider):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    procurando = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
    ).json()
    resposta = client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=pax.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    assert client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=intruso.headers).status_code == 403
    assert client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=rider.headers).status_code == 403
    assert client.post("/v1/rides/nao-existe/sos", headers=pax.headers).status_code == 404


def test_lista_e_encerramento_de_alertas_sao_so_do_administrador(client, pax, rider):
    for metodo, url in (("get", "/v1/admin/safety-alerts"), ("post", "/v1/admin/safety-alerts/1/resolve")):
        for quem in (pax, rider):
            assert getattr(client, metodo)(url, headers=quem.headers).status_code == 403
        assert getattr(client, metodo)(url).status_code == 401
    assert client.get("/v1/admin/safety-alerts", params={"status": "perdido"}, headers=rider.headers).status_code == 403


def test_estado_do_passageiro_traz_o_aviso_de_seguranca_em_aberto(client, pax, rider, clock, listen):
    # Revisão final (I4): o app que reconecta precisa redesenhar o "está tudo bem?".
    pedido = corrida(client, pax, rider)
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["safety_alert"] is None
    avisos = listen(pax.user_id)
    parar_por(client, rider, clock, 200)
    alerta = next(m for m in avisos.messages if m["type"] == "safety_check")["data"]
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]
    assert estado["safety_alert"] == {"alert_id": alerta["alert_id"], "kind": "stopped"}
    client.post(f"/v1/rides/{pedido['ride_id']}/safety/{alerta['alert_id']}/ok", headers=pax.headers)
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["safety_alert"] is None
