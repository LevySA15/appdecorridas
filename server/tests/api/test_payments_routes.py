import json

import pytest

from app.api.webhook import SIGNATURE_HEADER, sign
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import PaymentProviderError
from tests.api.conftest import WEBHOOK_SECRET
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


def corrida_aceita(client, pax, rider, metodo="pix"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    corrida = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    ).json()
    assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers).status_code == 200
    return corrida


def enviar(client, evento, segredo=WEBHOOK_SECRET, corpo=None, cabecalho=SIGNATURE_HEADER):
    corpo = json.dumps(evento).encode() if corpo is None else corpo
    return client.post("/v1/webhooks/pix", content=corpo, headers={cabecalho: sign(segredo, corpo)})


# --- aviso do provedor -----------------------------------------------------------------------


def test_aviso_de_pago_assinado_confirma_a_corrida_e_avisa_os_dois(client, pax, rider, runtime, session, listen):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    avisos_pax, avisos_rider = listen(pax.user_id), listen(rider.user_id)
    resposta = enviar(client, runtime.provider.mark_paid(cobranca))
    assert resposta.status_code == 200 and resposta.json() == {"status": "applied"}
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is True
    assert avisos_pax.types == ["pix_confirmed"] and avisos_rider.types == ["payment_received"]
    assert PgLedger(session).is_balanced() is True


def test_aviso_repetido_nao_cobra_nem_avisa_duas_vezes(client, pax, rider, runtime, session, listen):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    assert enviar(client, evento).json() == {"status": "applied"}
    avisos = listen(pax.user_id)
    assert enviar(client, evento).json() == {"status": "duplicate"}
    assert avisos.messages == []
    assert PgLedger(session).balance(f"rider:{rider.user_id}") == corrida["price_cents"] - 100


@pytest.mark.parametrize(
    "cabecalho, segredo",
    [(SIGNATURE_HEADER, "outro-segredo"), ("x-outra-coisa", WEBHOOK_SECRET)],
)
def test_aviso_com_assinatura_falsa_ou_ausente_e_recusado_sem_mexer_em_nada(
    client, pax, rider, runtime, session, cabecalho, segredo
):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    resposta = enviar(client, evento, segredo=segredo, cabecalho=cabecalho)
    assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "bad_signature"
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is False


def test_corpo_alterado_depois_de_assinado_e_recusado(client, pax, rider, runtime, session):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    original = json.dumps(evento).encode()
    assinatura = sign(WEBHOOK_SECRET, original)
    adulterado = original.replace(b'"amount_cents": ', b'"amount_cents": 1')
    resposta = client.post("/v1/webhooks/pix", content=adulterado, headers={SIGNATURE_HEADER: assinatura})
    assert resposta.status_code == 401


@pytest.mark.parametrize("campo, valor", [("amount_cents", 1), ("ride_id", "ride-de-outro")])
def test_aviso_que_nao_bate_com_a_cobranca_guardada_nao_e_aplicado(
    client, pax, rider, runtime, session, campo, valor
):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    resposta = enviar(client, evento | {campo: valor})
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "event_mismatch"
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is False
    assert enviar(client, evento).json() == {"status": "applied"}       # o aviso verdadeiro ainda vale: o id não foi gasto


def test_aviso_de_cobranca_desconhecida_e_confirmado_sem_efeito(client):
    evento = {"event_id": "evt-x", "type": "paid", "charge_id": "ch-fantasma", "ride_id": "ride-x", "amount_cents": 700}
    resposta = enviar(client, evento)
    assert resposta.status_code == 200 and resposta.json() == {"status": "unknown_charge"}


@pytest.mark.parametrize(
    "evento",
    [
        {"event_id": "e", "type": "refunded", "charge_id": "c", "ride_id": "r", "amount_cents": 1},
        {"event_id": "e", "type": "paid", "charge_id": "c", "ride_id": "r", "amount_cents": -5},
        {"event_id": "", "type": "paid", "charge_id": "c", "ride_id": "r", "amount_cents": 5},
        {"type": "paid"},
    ],
)
def test_aviso_mal_formado_e_422_mesmo_com_assinatura_certa(client, evento):
    assert enviar(client, evento).status_code == 422


def test_corpo_que_nao_e_json_e_corpo_gigante(client):
    assert enviar(client, None, corpo=b"isto nao e json").status_code == 422
    assert enviar(client, None, corpo=b"{" + b" " * 70_000 + b"}").status_code == 413


def test_pix_pago_depois_de_cancelar_e_devolvido_e_o_passageiro_e_avisado(
    client, pax, rider, runtime, session, listen
):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    assert client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers).status_code == 200
    avisos = listen(pax.user_id)
    assert enviar(client, runtime.provider.mark_paid(cobranca)).json() == {"status": "refunded"}
    assert avisos.types == ["payment_refunded"]
    assert runtime.provider.charges[cobranca].refunded is True


# --- ver a cobrança ------------------------------------------------------------------------------


def test_so_quem_participa_ve_a_cobranca_da_corrida(client, runtime, pax, rider, session):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    esperado = {
        "charge_id": cobranca, "purpose": "ride", "ride_id": corrida["ride_id"],
        "amount_cents": corrida["price_cents"], "paid": False, "br_code": f"fake-pix|{cobranca}|{corrida['price_cents']}",
    }
    assert client.get(f"/v1/charges/{cobranca}", headers=pax.headers).json() == esperado
    assert client.get(f"/v1/charges/{cobranca}", headers=rider.headers).json() == esperado
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    assert client.get(f"/v1/charges/{cobranca}", headers=intruso.headers).status_code == 403
    assert client.get(f"/v1/charges/{cobranca}").status_code == 401
    assert client.get("/v1/charges/nao-existe", headers=pax.headers).status_code == 404


def test_cobranca_da_entrada_e_so_do_motoqueiro(client, runtime, pax, rider):
    entrada = client.post("/v1/rider/entry-charge", headers=rider.headers).json()
    visto = client.get(f"/v1/charges/{entrada['charge_id']}", headers=rider.headers).json()
    assert visto["purpose"] == "entry" and visto["ride_id"] is None and visto["amount_cents"] == 5000
    assert client.get(f"/v1/charges/{entrada['charge_id']}", headers=pax.headers).status_code == 403


# --- provedor fora do ar -----------------------------------------------------------------------


def test_provedor_fora_do_ar_da_503_e_o_app_passa_a_oferecer_so_dinheiro(client, pax, rider, runtime, clock):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    corrida = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "pix"}, headers=pax.headers
    ).json()

    def fora_do_ar(*args, **kwargs):
        raise PaymentProviderError("timeout")

    runtime.provider.create_pix_charge = fora_do_ar
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers)
    assert resposta.status_code == 503 and resposta.json()["error"]["code"] == "payment_unavailable"
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["payment_methods"] == ["cash"]
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["state"] == "searching"
    clock.advance(61)
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["payment_methods"] == ["pix", "cash"]


# --- rotas só de desenvolvimento ----------------------------------------------------------------


def test_rota_de_desenvolvimento_devolve_o_ultimo_codigo_de_login(client, runtime):
    client.post("/v1/auth/code", json={"phone": "75 99999-1234"})
    codigo = runtime.otp_sender.last_code("+5575999991234")
    assert client.get("/v1/dev/otp", params={"phone": "75 99999-1234"}).json() == {"code": codigo}
    assert client.get("/v1/dev/otp", params={"phone": "75 98888-0000"}).status_code == 404


def test_rota_de_desenvolvimento_paga_um_pix_pelo_mesmo_caminho_do_aviso_real(client, pax, rider, session):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "applied"}
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is True
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "duplicate"}
    assert client.post("/v1/dev/pix/ch-fantasma/pay").status_code == 404


def test_fora_do_modo_dev_as_rotas_de_desenvolvimento_nem_existem(runtime):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.api.app import create_app

    producao = dataclasses.replace(runtime, mode="production")
    with TestClient(create_app(producao)) as cliente:
        assert cliente.get("/v1/dev/otp", params={"phone": "75 99999-1234"}).status_code == 404
        assert cliente.post("/v1/dev/pix/ch-1/pay").status_code == 404
        assert cliente.get("/docs").status_code == 404
