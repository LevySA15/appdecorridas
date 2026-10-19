"""Bloqueio por dívida do motoqueiro e a cobrança Pix para pagar a dívida, pela API."""
import pytest

from app.db import repositories as repo
from tests.api.helpers import login, online_rider, rider_phone


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def deve(session, cents=100):
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = cents
    repo.save_rider_account(session, acc)


def conta(client, rider):
    return client.get("/v1/rider/state", headers=rider.headers).json()["account"]


def test_estado_do_motoqueiro_explica_o_bloqueio_por_divida(client, rider, session):
    assert conta(client, rider)["blocked_reason"] is None and conta(client, rider)["debt_to_pay_cents"] == 0
    deve(session)
    corpo = conta(client, rider)
    assert corpo["blocked_reason"] == "debt_pending" and corpo["debt_to_pay_cents"] == 100
    assert (corpo["cash_debt_cents"], corpo["cash_debt_limit_cents"], corpo["needs_entry"]) == (100, 70, False)


def test_entrada_pendente_continua_aparecendo_como_entrada(client, rider, session):
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides, acc.cash_debt_cents = 10, 100
    repo.save_rider_account(session, acc)
    corpo = conta(client, rider)
    assert corpo["blocked_reason"] == "entry_pending" and corpo["needs_entry"] is True


def test_ficar_disponivel_com_divida_responde_debt_pending(client, rider, session):
    deve(session)
    client.post("/v1/rider/offline", headers=rider.headers)
    resposta = client.post("/v1/rider/online", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "debt_pending"
    assert "R$ 1,00" in resposta.json()["error"]["message"]


def test_pagar_a_divida_pela_api_destrava_e_o_motoqueiro_volta_a_ficar_disponivel(client, rider, session, listen):
    deve(session)
    client.post("/v1/rider/offline", headers=rider.headers)
    avisos = listen(rider.user_id)
    resposta = client.post("/v1/rider/debt-charge", headers=rider.headers)
    assert resposta.status_code == 201
    cobranca = resposta.json()
    assert cobranca["amount_cents"] == 100 and cobranca["br_code"]
    assert client.get(f"/v1/charges/{cobranca['charge_id']}", headers=rider.headers).json()["purpose"] == "debt"
    assert client.post(f"/v1/dev/pix/{cobranca['charge_id']}/pay").json() == {"status": "applied"}
    assert conta(client, rider)["blocked_reason"] is None and conta(client, rider)["cash_debt_cents"] == 0
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    assert avisos.types == ["debt_paid"]
    auditoria = client.get("/v1/dev/audit").json()
    assert auditoria["ledger_balanced"] is True and auditoria["reconcile_diff"] == {}


def test_sem_divida_nao_ha_cobranca(client, rider):
    resposta = client.post("/v1/rider/debt-charge", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"


def test_passageiro_nao_ve_a_cobranca_da_divida_nem_cria_uma(client, runtime, rider, session):
    deve(session)
    cobranca = client.post("/v1/rider/debt-charge", headers=rider.headers).json()
    pax = login(client, runtime, "75 99999-0001", "passenger")
    assert client.get(f"/v1/charges/{cobranca['charge_id']}", headers=pax.headers).status_code == 403
    assert client.post("/v1/rider/debt-charge", headers=pax.headers).status_code == 403
