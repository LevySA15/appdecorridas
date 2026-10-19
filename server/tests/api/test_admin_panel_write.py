"""Ações do painel do dono (bloquear passageiro, parâmetros) e o registro de tudo o que o administrador fez."""
import pytest

from app.db import repositories as repo
from app.db.models import AdminActionRow, RiderProfileRow, SafetyAlertRow
from tests.api.helpers import login, online_rider, rider_phone
from tests.api.test_admin_panel_read import QUOTE, admin, cancelada_tarde, pax, rider  # noqa: F401
from tests.helpers_db import add_in_progress_ride, add_passenger, add_rider

ESCRITAS = [
    ("post", "/v1/admin/passengers/x/block", {"reason": "teste"}),
    ("post", "/v1/admin/passengers/x/unblock", None),
    ("put", "/v1/admin/config/rides", {}),
]
LEITURAS = ["/v1/admin/config", "/v1/admin/actions"]


@pytest.mark.parametrize("metodo, rota, corpo", ESCRITAS)
def test_so_administrador_escreve_cada_rota(client, pax, rider, metodo, rota, corpo):
    chamar = getattr(client, metodo)
    assert chamar(rota, json=corpo).status_code == 401
    assert chamar(rota, json=corpo, headers=pax.headers).status_code == 403
    assert chamar(rota, json=corpo, headers=rider.headers).status_code == 403


@pytest.mark.parametrize("rota", LEITURAS)
def test_so_administrador_le_config_e_registro(client, pax, rota):
    assert client.get(rota).status_code == 401 and client.get(rota, headers=pax.headers).status_code == 403


def acoes(session):
    return [(a.action, a.target_type, a.target_id) for a in session.query(AdminActionRow).order_by(AdminActionRow.id)]


def test_bloquear_e_liberar_passageiro_impede_e_volta_a_permitir_pedido(client, pax, admin, session):
    url = f"/v1/admin/passengers/{pax.user_id}"
    assert client.post(f"{url}/block", json={"reason": "briga com motoqueiro"}, headers=admin.headers).status_code == 204
    pedido = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers)
    assert pedido.status_code in (401, 403)                       # conta bloqueada: o servidor já nega o acesso
    assert client.get("/v1/admin/passengers", headers=admin.headers).json()[0]["is_blocked"] is True
    assert client.post(f"{url}/unblock", headers=admin.headers).status_code == 204
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).status_code == 200
    assert acoes(session) == [("passenger.block", "passenger", pax.user_id), ("passenger.unblock", "passenger", pax.user_id)]
    assert session.query(AdminActionRow).first().detail == "briga com motoqueiro"
    assert client.post("/v1/admin/passengers/nao-existe/block", json={"reason": "x"}, headers=admin.headers).status_code == 404


def test_leitura_de_parametros_traz_todas_as_chaves_com_padroes(client, admin):
    corpo = client.get("/v1/admin/config", headers=admin.headers).json()
    assert set(corpo) == {"pricing", "fees", "rides", "dispatch", "safety", "auth", "balance"}
    assert corpo["rides"]["free_cancel_after_accept_s"] == 300 and corpo["balance"]["topup_enabled"] is False
    assert corpo["fees"]["tiers"][0] == {"from_ride": 1, "to_ride": 5, "fee_cents": 100}


def test_gravar_parametro_vale_na_hora_e_aparece_na_proxima_leitura(client, admin, session):
    corpo = client.get("/v1/admin/config", headers=admin.headers).json()["rides"] | {"free_cancel_after_accept_s": 120}
    assert client.put("/v1/admin/config/rides", json=corpo, headers=admin.headers).status_code == 204
    assert client.get("/v1/admin/config", headers=admin.headers).json()["rides"]["free_cancel_after_accept_s"] == 120
    assert acoes(session) == [("config.save", "config", "rides")]


@pytest.mark.parametrize(
    "chave, mudar, status",
    [
        ("rides", {"cancel_fee_min_cents": 600, "cancel_fee_max_cents": 500}, 422),
        ("fees", {"tiers": [{"from_ride": 1, "to_ride": None, "fee_cents": 10}]}, 422),
        ("rides", {"campo_que_nao_existe": 1}, 422),
        ("balance", {"topup_min_cents": 5000, "topup_max_cents": 1000}, 422),
        ("inventada", {}, 404),
    ],
)
def test_parametro_invalido_nunca_e_gravado_e_explica_em_portugues(client, admin, session, chave, mudar, status):
    atual = client.get("/v1/admin/config", headers=admin.headers).json()
    base = atual.get(chave, {})
    resposta = client.put(f"/v1/admin/config/{chave}", json=base | mudar, headers=admin.headers)
    assert resposta.status_code == status
    if status == 422:
        assert resposta.json()["error"]["code"] == "invalid" and resposta.json()["error"]["message"]
    assert client.get("/v1/admin/config", headers=admin.headers).json() == atual
    assert acoes(session) == []


def test_toda_escrita_deixa_registro_com_quem_fez(client, pax, rider, admin, session, clock, runtime):
    # recurso decidido (antes de mexer no motoqueiro, que precisa estar disponível para a corrida)
    ride_id = cancelada_tarde(client, pax, rider, clock, runtime)
    client.post(f"/v1/passenger/rides/{ride_id}/fee/appeal", json={"text": "A moto estava parada."}, headers=pax.headers)
    assert client.post(f"/v1/admin/appeals/{ride_id}/decide", json={"decision": "accept", "note": "ok"}, headers=admin.headers).status_code == 204
    # motoqueiros: recusar, aprovar, bloquear, liberar
    session.get(RiderProfileRow, "r1").status = "pending"
    session.flush()
    assert client.post("/v1/admin/riders/r1/reject", json={"reason": "foto ruim"}, headers=admin.headers).status_code == 204
    session.get(RiderProfileRow, "r1").status = "pending"          # cada chamada da API fecha a sessão: busca de novo
    session.flush()
    assert client.post("/v1/admin/riders/r1/approve", headers=admin.headers).status_code == 204
    assert client.post("/v1/admin/riders/r1/block", json={"reason": "denúncia"}, headers=admin.headers).status_code == 204
    assert client.post("/v1/admin/riders/r1/unblock", headers=admin.headers).status_code == 204
    # alerta de segurança resolvido
    add_passenger(session, "p9", "+5575900000099")
    add_rider(session, "r9", "+5575900000098", "999.999.999-99", "CNH9", "ZZZ9Z99")
    add_in_progress_ride(session, "ride-9", "p9", "r9")
    session.add(SafetyAlertRow(ride_id="ride-9", kind="stopped", created_at=1.0))
    session.flush()
    alerta = session.query(SafetyAlertRow).one()
    assert client.post(f"/v1/admin/safety-alerts/{alerta.id}/resolve", json={"note": "ok"}, headers=admin.headers).status_code == 204
    # passageiro e parâmetro
    assert client.post(f"/v1/admin/passengers/{pax.user_id}/block", json={"reason": "x"}, headers=admin.headers).status_code == 204
    base = client.get("/v1/admin/config", headers=admin.headers).json()["safety"]
    assert client.put("/v1/admin/config/safety", json=base, headers=admin.headers).status_code == 204
    registrados = [(a.action, a.admin_id) for a in session.query(AdminActionRow).order_by(AdminActionRow.id)]
    assert [a for a, _ in registrados] == [
        "appeal.accept", "rider.reject", "rider.approve", "rider.block", "rider.unblock", "alert.resolve",
        "passenger.block", "config.save",
    ]
    assert {quem for _, quem in registrados} == {admin.user_id}


def test_leitura_nao_deixa_registro(client, admin, session):
    for rota in ("/v1/admin/rides", "/v1/admin/money", "/v1/admin/config", "/v1/admin/riders", "/v1/admin/actions"):
        assert client.get(rota, headers=admin.headers).status_code == 200
    assert acoes(session) == []


def test_acao_que_falha_nao_deixa_registro(client, admin, session):
    assert client.post("/v1/admin/riders/nao-existe/approve", headers=admin.headers).status_code in (404, 409, 422)
    assert client.post("/v1/admin/appeals/nao-existe/decide", json={"decision": "accept", "note": ""}, headers=admin.headers).status_code == 404
    assert acoes(session) == []


def test_registro_lista_mais_novo_primeiro_com_nome_do_administrador(client, pax, admin, clock):
    client.post(f"/v1/admin/passengers/{pax.user_id}/block", json={"reason": "a"}, headers=admin.headers)
    clock.advance(10)
    client.post(f"/v1/admin/passengers/{pax.user_id}/unblock", headers=admin.headers)
    lista = client.get("/v1/admin/actions", headers=admin.headers).json()
    assert [a["action"] for a in lista] == ["passenger.unblock", "passenger.block"]
    assert lista[0]["admin_name"] == "Levy" and lista[0]["at"] > lista[1]["at"]
    assert set(lista[0]) == {"id", "admin_id", "admin_name", "action", "target_type", "target_id", "detail", "at"}
    assert len(client.get("/v1/admin/actions", params={"limit": 1}, headers=admin.headers).json()) == 1


@pytest.mark.parametrize(
    "chave, mudar",
    [
        ("pricing", {"base_fare_cents": "3,00"}),
        ("pricing", {"per_km_cents": -150}),
        ("pricing", {"min_price_cents": 0}),
        ("pricing", {"factor_min": 2.0, "factor_max": 1.0}),
        ("dispatch", {"offer_timeout_s": 0}),
        ("dispatch", {"max_candidates_routed": "3"}),
        ("safety", {"stopped_after_s": -1}),
        ("safety", {"no_signal_short_s": 300, "no_signal_mid_s": 240}),
        ("auth", {"otp_digits": "6"}),
        ("auth", {"otp_max_attempts": 0}),
        ("auth", {"otp_ttl_s": -1}),
        ("auth", {"session_days": 0}),
        ("rides", {"pix_window_s": True}),
        ("rides", {"max_trip_m": 50}),
        ("balance", {"topup_enabled": "sim"}),
        ("fees", {"tiers": [{"from_ride": 1, "to_ride": None, "fee_cents": "100"}]}),
    ],
)
def test_valor_de_tipo_errado_ou_fora_da_faixa_nunca_e_gravado(client, admin, session, chave, mudar):
    atual = client.get("/v1/admin/config", headers=admin.headers).json()
    resposta = client.put(f"/v1/admin/config/{chave}", json=atual[chave] | mudar, headers=admin.headers)
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["error"]["code"] == "invalid" and resposta.json()["error"]["message"]
    assert client.get("/v1/admin/config", headers=admin.headers).json() == atual
    assert acoes(session) == []


@pytest.mark.parametrize("chave", ["pricing", "fees", "rides", "dispatch", "safety", "auth", "balance"])
def test_corpo_vazio_nao_grava_os_padroes_sem_querer(client, admin, session, chave):
    assert client.put(f"/v1/admin/config/{chave}", json={}, headers=admin.headers).status_code == 422
    assert acoes(session) == []


def test_parametro_certo_continua_sendo_gravado_apos_as_validacoes_novas(client, admin):
    atual = client.get("/v1/admin/config", headers=admin.headers).json()
    for chave, valor in atual.items():
        assert client.put(f"/v1/admin/config/{chave}", json=valor, headers=admin.headers).status_code == 204, chave
