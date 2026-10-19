"""Leituras do painel do dono: corridas, passageiros, devedores e dinheiro."""
import pytest

from app.db import queries
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
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


def cancelada_tarde(client, pax, rider, clock, runtime, metodo="cash"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    ride_id = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    ).json()["ride_id"]
    assert client.post(f"/v1/rider/offers/{ride_id}/accept", headers=rider.headers).status_code == 200
    if metodo == "pix":
        client.post(f"/v1/dev/pix/{next(iter(runtime.provider.charges))}/pay")
    clock.advance(301)
    assert client.post(f"/v1/passenger/rides/{ride_id}/cancel", headers=pax.headers).status_code == 200
    return ride_id


ROTAS = ["/v1/admin/rides", "/v1/admin/rides/x", "/v1/admin/passengers", "/v1/admin/debtors", "/v1/admin/money"]


@pytest.mark.parametrize("rota", ROTAS)
def test_so_administrador_le_cada_rota(client, pax, rider, rota):
    assert client.get(rota).status_code == 401
    assert client.get(rota, headers=pax.headers).status_code == 403
    assert client.get(rota, headers=rider.headers).status_code == 403


def test_lista_de_corridas_mostra_nomes_estado_e_filtra_por_estado(client, pax, rider, admin, clock, runtime):
    ride_id = cancelada_tarde(client, pax, rider, clock, runtime)
    lista = client.get("/v1/admin/rides", headers=admin.headers).json()
    assert len(lista) == 1
    item = lista[0]
    assert (item["ride_id"], item["state"], item["method"]) == (ride_id, "cancelled", "cash")
    assert (item["passenger_name"], item["pickup_text"], item["dest_text"]) == ("Ana Lima", "Rua A", "Feira livre")
    assert item["rider_name"] and item["price_cents"] > 0 and isinstance(item["created_at"], float)
    assert len(client.get("/v1/admin/rides", params={"state": "cancelled"}, headers=admin.headers).json()) == 1
    assert client.get("/v1/admin/rides", params={"state": "completed"}, headers=admin.headers).json() == []
    assert client.get("/v1/admin/rides", params={"state": "inventado"}, headers=admin.headers).status_code == 422


def test_detalhe_da_corrida_traz_historico_e_taxa_de_cancelamento(client, pax, rider, admin, clock, runtime):
    ride_id = cancelada_tarde(client, pax, rider, clock, runtime)
    corpo = client.get(f"/v1/admin/rides/{ride_id}", headers=admin.headers).json()
    assert corpo["ride_id"] == ride_id and corpo["state"] == "cancelled" and "pin" not in corpo
    tipos = [e["kind"] for e in corpo["events"]]
    assert tipos[0] == "requested" and "accepted" in tipos and tipos[-1] == "cancelled"
    assert all(isinstance(e["at"], float) for e in corpo["events"])
    assert corpo["cancel_fee"] == {
        "fee_cents": 300, "from_balance_cents": 0, "retained_cents": 0, "pending_cents": 300,
        "paid_later_cents": 0, "appeal_state": "none",
    }
    assert client.get("/v1/admin/rides/nao-existe", headers=admin.headers).status_code == 404


def test_busca_de_passageiros_por_nome_e_telefone(client, pax, admin):
    todos = client.get("/v1/admin/passengers", headers=admin.headers).json()
    assert [p["name"] for p in todos] == ["Ana Lima"]
    assert set(todos[0]) == {"user_id", "name", "phone", "is_blocked", "unpaid_cents", "balance_cents", "created_at"}
    for busca, achou in (("ana", 1), ("99990001", 1), ("zzz", 0)):
        assert len(client.get("/v1/admin/passengers", params={"q": busca}, headers=admin.headers).json()) == achou


def test_devedores_listam_motoqueiro_com_divida_e_passageiro_com_pendencia(client, pax, rider, admin, clock, runtime, session):
    assert client.get("/v1/admin/debtors", headers=admin.headers).json() == {"riders": [], "passengers": []}
    cancelada_tarde(client, pax, rider, clock, runtime)
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 100
    repo.save_rider_account(session, acc)
    corpo = client.get("/v1/admin/debtors", headers=admin.headers).json()
    assert [(r["rider_id"], r["cash_debt_cents"]) for r in corpo["riders"]] == [("r1", 100)]
    assert [(p["name"], p["unpaid_cents"], p["pending_fee_cents"]) for p in corpo["passengers"]] == [("Ana Lima", 300, 300)]


def test_dinheiro_bate_com_o_livro(client, pax, rider, admin, clock, runtime, session):
    cancelada_tarde(client, pax, rider, clock, runtime, metodo="pix")        # Pix pago e cancelado tarde: taxa retida
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 100
    repo.save_rider_account(session, acc)
    corpo = client.get("/v1/admin/money", headers=admin.headers).json()
    livro = PgLedger(session)
    assert corpo["company_cents"] == livro.balance(PgLedger.COMPANY)
    assert corpo["provider_cents"] == livro.balance(PgLedger.PROVIDER) and corpo["provider_cents"] < 0
    assert corpo["riders_cents"] == livro.balance("rider:r1") == 300
    assert corpo["passenger_balances_cents"] == queries.passenger_balances_total(session) == queries.ledger_balances_total(session)
    assert corpo["rider_debts_cents"] == 100 and corpo["pending_fees_cents"] == 0 and corpo["passenger_unpaid_cents"] == 0
    assert corpo["ledger_balanced"] is True and corpo["rides_by_state"] == {"cancelled": 1}


def test_paginacao_respeita_limit_e_offset(client, pax, rider, admin, clock, runtime):
    cancelada_tarde(client, pax, rider, clock, runtime)
    assert len(client.get("/v1/admin/rides", params={"limit": 1}, headers=admin.headers).json()) == 1
    assert client.get("/v1/admin/rides", params={"limit": 1, "offset": 1}, headers=admin.headers).json() == []
    assert client.get("/v1/admin/rides", params={"limit": 0}, headers=admin.headers).status_code == 422


def test_lista_vazia_devolve_lista_vazia(client, admin):
    assert client.get("/v1/admin/rides", headers=admin.headers).json() == []
    assert client.get("/v1/admin/passengers", headers=admin.headers).json() == []
    assert client.get("/v1/admin/money", headers=admin.headers).json()["rides_by_state"] == {}
