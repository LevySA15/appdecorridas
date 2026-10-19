"""A conferência de fim de dia que o simulador pede ao servidor (só no modo de desenvolvimento)."""
import dataclasses

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.app import create_app
from app.domain.payments import Split
from tests.api.test_payments_routes import corrida_aceita, pax, rider  # noqa: F401
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_sem_nada_a_auditoria_fecha_e_nao_tem_corrida_aberta(client):
    corpo = client.get("/v1/dev/audit").json()
    assert corpo == {
        "ledger_balanced": True, "reconcile_diff": {}, "rides_by_state": {}, "open_rides": [],
        "double_booked_riders": [], "balance_matches_ledger": True, "inconsistent_fees": [],
    }


def test_corrida_em_andamento_aparece_como_aberta_e_o_pix_pago_bate_com_o_livro(client, pax, rider, runtime):
    corrida = corrida_aceita(client, pax, rider)
    antes = client.get("/v1/dev/audit").json()
    assert antes["rides_by_state"] == {"accepted": 1}
    assert [(r["ride_id"], r["state"]) for r in antes["open_rides"]] == [(corrida["ride_id"], "accepted")]
    cobranca = next(iter(runtime.provider.charges))
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "applied"}
    depois = client.get("/v1/dev/audit").json()
    assert depois["ledger_balanced"] is True and depois["reconcile_diff"] == {}


def test_pix_pago_no_provedor_que_o_livro_nao_conhece_aparece_na_diferenca(client, runtime):
    cobranca = runtime.provider.create_pix_charge("ride-x", "r1", 700, Split(600, 100, 0))
    runtime.provider.mark_paid(cobranca.charge_id)             # pago lá, mas o aviso nunca chegou aqui
    assert client.get("/v1/dev/audit").json()["reconcile_diff"] == {f"charge:{cobranca.charge_id}": 700}


def test_motoqueiro_com_duas_corridas_ativas_e_denunciado(client, session):
    add_passenger(session, "p1", "+5575900000001")
    add_passenger(session, "p2", "+5575900000003")
    add_rider(session, "r1")
    add_accepted_ride(session, "ride-1", "p1", "r1")
    add_accepted_ride(session, "ride-2", "p2", "r1")
    assert client.get("/v1/dev/audit").json()["double_booked_riders"] == ["r1"]


def test_fora_do_modo_dev_a_auditoria_nem_existe(runtime):
    producao = dataclasses.replace(runtime, mode="production")
    with TestClient(create_app(producao)) as cliente:
        assert cliente.get("/v1/dev/audit").status_code == 404


def test_cancelamento_tardio_com_pix_pago_continua_batendo_com_o_extrato_do_provedor(client, pax, rider, runtime, clock):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = next(iter(runtime.provider.charges))
    client.post(f"/v1/dev/pix/{cobranca}/pay")
    clock.advance(301)
    client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers)
    depois = client.get("/v1/dev/audit").json()
    assert depois["ledger_balanced"] is True and depois["reconcile_diff"] == {}
    assert runtime.provider.charges[cobranca].refunded_cents < runtime.provider.charges[cobranca].amount_cents


def test_conferencia_acusa_saldo_diferente_do_livro(client, session):
    add_passenger(session, "p1", "+5575900000001")
    session.execute(text("UPDATE passenger_profiles SET balance_cents = 500 WHERE user_id = 'p1'"))
    assert client.get("/v1/dev/audit").json()["balance_matches_ledger"] is False
