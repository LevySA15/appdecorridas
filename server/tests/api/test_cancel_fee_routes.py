"""Taxa de cancelamento tardio, pendência, recurso e decisão do administrador pela API."""
import pytest

from app.db import repositories as repo
from app.db.config_store import save_config
from app.domain.config import BalanceConfig
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}
TEXTO = {"text": "A moto ficou parada na esquina."}


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


def aceita(client, pax, rider, metodo="cash"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    corrida = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    ).json()
    assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers).status_code == 200
    return corrida["ride_id"]


def cancelar_tarde(client, pax, rider, clock, metodo="cash"):
    ride_id = aceita(client, pax, rider, metodo)
    clock.advance(301)
    resposta = client.post(f"/v1/passenger/rides/{ride_id}/cancel", headers=pax.headers)
    assert resposta.status_code == 200, resposta.text
    return ride_id, resposta.json()


def estado(client, quem):
    return client.get("/v1/passenger/state", headers=quem.headers).json()


def test_visao_da_corrida_mostra_o_fim_da_janela_e_a_taxa_de_agora(client, pax, rider, clock):
    aceitou_em = clock.now
    aceita(client, pax, rider)
    assert estado(client, pax)["ride"]["cancel"] == {"free_until": aceitou_em + 300, "fee_cents_now": 0}
    clock.advance(301)
    assert estado(client, pax)["ride"]["cancel"] == {"free_until": aceitou_em + 300, "fee_cents_now": 300}


def test_cancelar_tarde_com_a_moto_parada_no_lugar_nao_cobra_nada(client, pax, rider, clock, session):
    ride_id = aceita(client, pax, rider)
    clock.advance(301)
    ponto = pt(300, 0)                     # onde a moto estava ao aceitar: ela não saiu de lá
    assert client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers).status_code == 204
    assert estado(client, pax)["ride"]["cancel"]["fee_cents_now"] == 0
    resposta = client.post(f"/v1/passenger/rides/{ride_id}/cancel", headers=pax.headers)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"refund": False, "fee_cents": 0, "fee": None, "refund_to": None, "balance_cents": 0}
    assert estado(client, pax).get("blocked_reason") is None


def test_corrida_ainda_sem_moto_nao_tem_janela(client, pax, session, runtime, clock):
    online_rider(session, runtime, clock, 1)
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    client.post("/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers)
    assert estado(client, pax)["ride"]["cancel"] is None


def test_cancelar_dentro_da_janela_responde_sem_taxa(client, pax, rider):
    ride_id = aceita(client, pax, rider)
    resposta = client.post(f"/v1/passenger/rides/{ride_id}/cancel", headers=pax.headers)
    assert resposta.json() == {"refund": False, "fee_cents": 0, "fee": None, "refund_to": None, "balance_cents": 0}


def test_cancelar_tarde_responde_a_taxa_e_o_destino_do_dinheiro(client, pax, rider, clock):
    _, corpo = cancelar_tarde(client, pax, rider, clock)
    assert corpo == {
        "refund": False, "fee_cents": 300, "balance_cents": 0, "refund_to": None,
        "fee": {"from_balance_cents": 0, "retained_cents": 0, "pending_cents": 300},
    }


def test_cancelar_tarde_com_pix_pago_retem_a_taxa_e_devolve_o_resto(client, pax, rider, clock, runtime):
    ride_id = aceita(client, pax, rider, "pix")
    cobranca = next(iter(runtime.provider.charges))
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "applied"}
    clock.advance(301)
    corpo = client.post(f"/v1/passenger/rides/{ride_id}/cancel", headers=pax.headers).json()
    assert (corpo["refund"], corpo["fee_cents"], corpo["refund_to"]) == (True, 300, "pix")
    assert corpo["fee"] == {"from_balance_cents": 0, "retained_cents": 300, "pending_cents": 0}


def test_estado_mostra_pendencia_e_pedido_novo_e_bloqueado(client, pax, rider, clock):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    corpo = estado(client, pax)
    assert corpo["balance_cents"] == 0 and corpo["topup_enabled"] is False
    assert corpo["pending_fee"] == {"ride_id": ride_id, "amount_cents": 300, "charge_id": None, "appeal": None}
    assert corpo["blocked_reason"] == "Falta pagar a taxa do cancelamento. Pague para pedir outra moto."
    assert corpo["recent_fees"] == [{
        "ride_id": ride_id, "fee_cents": 300, "created_at": clock.now, "from_balance_cents": 0,
        "retained_cents": 0, "pending_cents": 300, "appeal_state": "none", "can_appeal": True,
    }]
    pedido = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers)
    assert pedido.status_code == 403 and pedido.json()["error"]["code"] == "not_allowed"


def test_pagar_a_pendencia_pelo_pix_desbloqueia(client, pax, rider, clock, listen):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    avisos = listen(pax.user_id)
    resposta = client.post("/v1/passenger/fees/pay", headers=pax.headers)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["paid"] is False and corpo["amount_cents"] == 300 and corpo["br_code"]
    assert client.get(f"/v1/charges/{corpo['charge_id']}", headers=pax.headers).json()["purpose"] == "fee"
    assert estado(client, pax)["pending_fee"]["charge_id"] == corpo["charge_id"]
    assert client.post(f"/v1/dev/pix/{corpo['charge_id']}/pay").json() == {"status": "applied"}
    depois = estado(client, pax)
    assert depois["pending_fee"] is None and depois["blocked_reason"] is None and depois["unpaid_cents"] == 0
    assert avisos.types == ["fee_paid", "unblocked"]
    assert client.post("/v1/passenger/fees/pay", headers=pax.headers).json()["error"]["code"] == "nothing_to_pay"
    assert ride_id


def test_pagar_a_pendencia_com_saldo_nao_gera_cobranca(client, pax, rider, clock, session, runtime):
    cancelar_tarde(client, pax, rider, clock)
    save_config(session, "balance", BalanceConfig(topup_enabled=True, topup_min_cents=100))
    runtime._config = None
    recarga = client.post("/v1/passenger/balance/topup", json={"amount_cents": 1000}, headers=pax.headers).json()
    client.post(f"/v1/dev/pix/{recarga['charge_id']}/pay")
    assert estado(client, pax)["balance_cents"] == 1000
    assert client.post("/v1/passenger/fees/pay", headers=pax.headers).json() == {"paid": True}
    corpo = estado(client, pax)
    assert corpo["balance_cents"] == 700 and corpo["pending_fee"] is None and corpo["blocked_reason"] is None


def test_sem_pendencia_nao_ha_o_que_pagar(client, pax):
    resposta = client.post("/v1/passenger/fees/pay", headers=pax.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "nothing_to_pay"


def test_recurso_pela_api_e_decisao_do_administrador(client, pax, rider, admin, clock, listen):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    avisos_pax, avisos_admin = listen(pax.user_id), listen(admin.user_id)
    assert client.post(f"/v1/passenger/rides/{ride_id}/fee/appeal", json=TEXTO, headers=pax.headers).status_code == 204
    assert avisos_admin.types == ["appeal_opened"]
    fila = client.get("/v1/admin/appeals", params={"status": "open"}, headers=admin.headers).json()
    assert len(fila) == 1
    assert (fila[0]["ride_id"], fila[0]["fee_cents"], fila[0]["appeal_text"], fila[0]["passenger_name"]) == (
        ride_id, 300, TEXTO["text"], "Ana Lima",
    )
    assert estado(client, pax)["pending_fee"]["appeal"]["state"] == "open"
    decisao = client.post(
        f"/v1/admin/appeals/{ride_id}/decide", json={"decision": "accept", "note": "Procede."}, headers=admin.headers
    )
    assert decisao.status_code == 204
    depois = estado(client, pax)
    assert depois["pending_fee"] is None and depois["blocked_reason"] is None
    assert depois["recent_fees"][0]["appeal_state"] == "accepted" and depois["recent_fees"][0]["can_appeal"] is False
    assert avisos_pax.types == ["appeal_decided", "unblocked"]
    assert client.get("/v1/admin/appeals", params={"status": "open"}, headers=admin.headers).json() == []
    assert len(client.get("/v1/admin/appeals", params={"status": "accepted"}, headers=admin.headers).json()) == 1


def test_recurso_repetido_de_outro_ou_sem_taxa_tem_erro_claro(client, runtime, pax, rider, clock):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    url = f"/v1/passenger/rides/{ride_id}/fee/appeal"
    assert client.post(url, json=TEXTO, headers=pax.headers).status_code == 204
    repetido = client.post(url, json=TEXTO, headers=pax.headers)
    assert repetido.status_code == 409 and repetido.json()["error"]["code"] == "appeal_not_allowed"
    outro = login(client, runtime, "75 99999-0005", "passenger")
    assert client.post(url, json=TEXTO, headers=outro.headers).json()["error"]["code"] == "not_your_ride"
    assert client.post("/v1/passenger/rides/nao-existe/fee/appeal", json=TEXTO, headers=pax.headers).status_code == 404
    assert client.post(url, json={"text": "oi"}, headers=pax.headers).status_code in (409, 422)
    assert client.post(url, json={"text": ""}, headers=pax.headers).status_code == 422


def test_so_administrador_ve_e_decide_recursos(client, pax, rider, clock):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    assert client.get("/v1/admin/appeals", headers=pax.headers).status_code == 403
    assert client.get("/v1/admin/appeals").status_code == 401
    corpo = {"decision": "accept", "note": ""}
    assert client.post(f"/v1/admin/appeals/{ride_id}/decide", json=corpo, headers=pax.headers).status_code == 403


def test_decisao_invalida_ou_de_recurso_nao_aberto_e_recusada(client, pax, rider, admin, clock):
    ride_id, _ = cancelar_tarde(client, pax, rider, clock)
    url = f"/v1/admin/appeals/{ride_id}/decide"
    assert client.post(url, json={"decision": "talvez", "note": ""}, headers=admin.headers).status_code == 422
    nao_aberto = client.post(url, json={"decision": "accept", "note": ""}, headers=admin.headers)
    assert nao_aberto.status_code == 409 and nao_aberto.json()["error"]["code"] == "appeal_not_allowed"
    assert client.post("/v1/admin/appeals/nao-existe/decide", json={"decision": "reject", "note": ""},
                       headers=admin.headers).status_code == 404
