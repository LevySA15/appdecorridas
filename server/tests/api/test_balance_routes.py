"""Recarga do saldo do passageiro (desligada por padrão)."""
import pytest

from app.db.config_store import save_config
from app.domain.config import BalanceConfig
from tests.api.helpers import login


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


def ligar(session, runtime, **mudancas):
    save_config(session, "balance", BalanceConfig(topup_enabled=True, **mudancas))
    runtime._config = None


def test_recarga_desligada_por_padrao_responde_erro_claro(client, pax):
    resposta = client.post("/v1/passenger/balance/topup", json={"amount_cents": 2000}, headers=pax.headers)
    assert resposta.status_code == 403
    assert resposta.json()["error"]["code"] == "topup_disabled"
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["topup_enabled"] is False


def test_recarga_ligada_gera_cobranca_e_credita_o_saldo(client, pax, session, runtime, listen):
    ligar(session, runtime)
    avisos = listen(pax.user_id)
    resposta = client.post("/v1/passenger/balance/topup", json={"amount_cents": 2000}, headers=pax.headers)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["amount_cents"] == 2000 and corpo["br_code"]
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["topup_enabled"] is True
    assert client.post(f"/v1/dev/pix/{corpo['charge_id']}/pay").json() == {"status": "applied"}
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["balance_cents"] == 2000
    assert avisos.types == ["balance_changed"]
    assert client.get("/v1/dev/audit").json()["balance_matches_ledger"] is True


def test_so_o_dono_ve_a_cobranca_de_recarga(client, pax, session, runtime):
    ligar(session, runtime)
    cobranca = client.post("/v1/passenger/balance/topup", json={"amount_cents": 2000}, headers=pax.headers).json()
    url = f"/v1/charges/{cobranca['charge_id']}"
    corpo = client.get(url, headers=pax.headers).json()
    assert (corpo["purpose"], corpo["ride_id"], corpo["amount_cents"]) == ("topup", None, 2000)
    outro = login(client, runtime, "75 99999-0005", "passenger")
    assert client.get(url, headers=outro.headers).status_code == 403


@pytest.mark.parametrize("valor", [999, 20_001, 0, -5])
def test_recarga_fora_dos_limites_e_recusada(client, pax, session, runtime, valor):
    ligar(session, runtime)
    resposta = client.post("/v1/passenger/balance/topup", json={"amount_cents": valor}, headers=pax.headers)
    assert resposta.status_code == 422 and "R$ 10,00 a R$ 200,00" in resposta.json()["error"]["message"]


def test_recarga_com_valor_que_nao_e_numero_inteiro_e_recusada(client, pax, session, runtime):
    ligar(session, runtime)
    for corpo in ({"amount_cents": "muito"}, {"amount_cents": 20.5}, {}):
        assert client.post("/v1/passenger/balance/topup", json=corpo, headers=pax.headers).status_code == 422


def test_motoqueiro_nao_recarrega_saldo(client, runtime, session):
    ligar(session, runtime)
    outro = login(client, runtime, "75 99999-0007", "rider")
    assert client.post("/v1/passenger/balance/topup", json={"amount_cents": 2000}, headers=outro.headers).status_code == 403


# --- pagar a corrida com o saldo ---------------------------------------------------------------


def _lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


def _cotar(client, pax):
    from tests.helpers import ORIGIN, pt

    corpo = {"pickup": _lugar(ORIGIN, "Rua A"), "destination": _lugar(pt(1500, 0), "Feira livre")}
    return client.post("/v1/passenger/quotes", json=corpo, headers=pax.headers).json()


def _recarregar(client, pax, session, runtime, valor=2000):
    ligar(session, runtime)
    cobranca = client.post("/v1/passenger/balance/topup", json={"amount_cents": valor}, headers=pax.headers).json()
    assert client.post(f"/v1/dev/pix/{cobranca['charge_id']}/pay").json() == {"status": "applied"}


def test_rota_recusa_pagar_com_saldo_sem_saldo(client, pax):
    cotacao = _cotar(client, pax)
    resposta = client.post(
        "/v1/passenger/rides", json={"quote_id": cotacao["quote_id"], "method": "balance"}, headers=pax.headers
    )
    assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "not_allowed"
    assert "saldo" in resposta.json()["error"]["message"]


def test_rota_aceita_method_balance_com_saldo_que_cobre(client, pax, session, runtime):
    _recarregar(client, pax, session, runtime)
    cotacao = _cotar(client, pax)
    resposta = client.post(
        "/v1/passenger/rides", json={"quote_id": cotacao["quote_id"], "method": "balance"}, headers=pax.headers
    )
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["method"] == "pix"
