"""Um usuário mexendo no que é de OUTRO usuário (IDOR): cada rota que recebe um id de corrida, cobrança ou motoqueiro é
chamada por quem não participa dela. Esperado: 403 ou 404, nada vaza e a corrida de verdade não muda."""
import pytest

from tests.api.helpers import login, online_rider, rider_phone
from tests.api.test_rider_routes import QUOTE, aceitar, pagar_pix, pedir

NEGADO = (403, 404)


@pytest.fixture()
def cena(client, runtime, session, clock):
    """Ana pediu uma corrida em Pix e o Rui a aceitou; Bia e o Léo são de fora."""
    online_rider(session, runtime, clock, 1)
    online_rider(session, runtime, clock, 2)
    ana = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    bia = login(client, runtime, "75 99999-0002", "passenger", name="Bia Souza")
    rui = login(client, runtime, rider_phone(1), "rider")
    leo = login(client, runtime, rider_phone(2), "rider")
    ride_id = pedir(client, ana, "pix")["ride_id"]
    aceitar(client, rui, ride_id)
    estado = client.get("/v1/passenger/state", headers=ana.headers).json()["ride"]
    return {"ana": ana, "bia": bia, "rui": rui, "leo": leo, "ride_id": ride_id, "charge_id": estado["pay"]["charge_id"], "rider_id": rui.user_id}


def _sem_mudanca(client, cena):
    estado = client.get("/v1/passenger/state", headers=cena["ana"].headers).json()["ride"]
    assert estado["ride_id"] == cena["ride_id"] and estado["state"] == "accepted"


@pytest.mark.parametrize(
    "metodo, caminho, corpo",
    [
        ("POST", "/v1/passenger/rides/{ride}/cancel", None),
        ("POST", "/v1/rides/{ride}/sos", None),
        ("POST", "/v1/rides/{ride}/rating", {"stars": 1}),
        ("POST", "/v1/rides/{ride}/safety/1/ok", None),
    ],
)
def test_passageiro_de_fora_nao_mexe_na_corrida_dos_outros(client, cena, metodo, caminho, corpo):
    url = caminho.format(ride=cena["ride_id"])
    resposta = client.request(metodo, url, json=corpo, headers=cena["bia"].headers)
    assert resposta.status_code in NEGADO, f"{metodo} {url}: {resposta.status_code} {resposta.text[:150]}"
    assert "Rui" not in resposta.text and "Ana" not in resposta.text
    _sem_mudanca(client, cena)


@pytest.mark.parametrize("nome", ["arrive", "helmet", "start", "complete", "sos", "cash-received"])
def test_motoqueiro_de_fora_nao_mexe_na_corrida_dos_outros(client, cena, nome):
    url = f"/v1/rider/rides/{cena['ride_id']}/{nome}"
    resposta = client.post(url, json={"pin": "0000"}, headers=cena["leo"].headers)
    assert resposta.status_code in NEGADO, f"{url}: {resposta.status_code} {resposta.text[:150]}"
    _sem_mudanca(client, cena)


def test_motoqueiro_de_fora_nao_aceita_nem_recusa_a_oferta_de_outro(client, cena):
    for nome in ("accept", "decline"):
        resposta = client.post(f"/v1/rider/offers/{cena['ride_id']}/{nome}", headers=cena["leo"].headers)
        assert resposta.status_code in (403, 404, 409), f"{nome}: {resposta.status_code}"
    _sem_mudanca(client, cena)


def test_cobranca_so_quem_esta_na_corrida_ve(client, cena):
    charge = f"/v1/charges/{cena['charge_id']}"
    for quem in ("ana", "rui"):         # o passageiro e o motoqueiro dela (que cobra o fim da corrida)
        assert client.get(charge, headers=cena[quem].headers).status_code == 200
    for quem in ("bia", "leo"):
        resposta = client.get(charge, headers=cena[quem].headers)
        assert resposta.status_code in NEGADO, f"{quem}: {resposta.status_code} {resposta.text[:120]}"
        assert "br_code" not in resposta.text


@pytest.mark.parametrize("quem, kind, esperado", [
    ("ana", "selfie", 200),      # quem anda com ele vê a selfie
    ("ana", "cnh", 403),         # mas nunca os documentos
    ("ana", "crlv", 403),
    ("bia", "selfie", 403),      # quem nunca andou com ele não vê nada
    ("bia", "cnh", 403),
    ("leo", "selfie", 403),      # outro motoqueiro também não
    ("leo", "cnh", 403),
    ("rui", "cnh", 200),         # o dono vê tudo dele
])
def test_documentos_do_motoqueiro(client, runtime, session, cena, quem, kind, esperado):
    from app.db.models import RiderProfileRow

    png = b"\x89PNG\r\n\x1a\n" + b"corpo-do-documento"
    perfil = session.get(RiderProfileRow, cena["rider_id"])
    campo = {"selfie": "selfie_key", "cnh": "cnh_photo_key", "crlv": "crlv_key"}[kind]
    setattr(perfil, campo, runtime.documents.save(cena["rider_id"], kind, png))
    session.flush()
    resposta = client.get(f"/v1/riders/{cena['rider_id']}/documents/{kind}", headers=cena[quem].headers)
    assert resposta.status_code == esperado, f"{quem} {kind}: {resposta.status_code} {resposta.text[:100]}"
    if esperado == 200:
        assert resposta.content == png
        assert resposta.headers["cache-control"].startswith("private")


def test_dono_do_documento_so_com_o_proprio_id(client, cena):
    """Trocar o id na URL pelo de outro motoqueiro não abre o documento dele."""
    resposta = client.get(f"/v1/riders/{cena['leo'].user_id}/documents/cnh", headers=cena["rui"].headers)
    assert resposta.status_code in NEGADO


def test_estado_de_um_nao_mostra_a_corrida_do_outro(client, cena):
    assert client.get("/v1/passenger/state", headers=cena["bia"].headers).json()["ride"] is None
    estado_leo = client.get("/v1/rider/state", headers=cena["leo"].headers).json()
    assert estado_leo["ride"] is None and estado_leo["offer"] is None
