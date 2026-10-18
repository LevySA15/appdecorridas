import pytest
from fastapi import Depends

from app.api.deps import admin_user, passenger_user, rider_user
from app.db import repositories as repo
from app.db.config_store import save_config
from app.db.models import SessionRow, UserRow
from app.domain.config import AuthConfig
from app.services.auth import normalize_phone
from tests.api.helpers import login

PHONE = "75 99999-1234"


def _pedir_codigo(client, runtime, phone=PHONE) -> str:
    assert client.post("/v1/auth/code", json={"phone": phone}).status_code == 204
    return runtime.otp_sender.last_code(normalize_phone(phone))


def test_entrar_ver_meus_dados_dar_nome_e_sair(client, runtime):
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post(
        "/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger", "device": "Moto G"}
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["role"] == "passenger" and corpo["is_new_user"] is True and corpo["name"] == ""
    cabecalho = {"Authorization": f"Bearer {corpo['token']}"}

    assert client.get("/v1/me", headers=cabecalho).json() == {
        "user_id": corpo["user_id"], "phone": "+5575999991234", "name": "", "role": "passenger",
    }
    assert client.put("/v1/me", json={"name": " Ana Lima "}, headers=cabecalho).json()["name"] == "Ana Lima"
    assert client.post("/v1/auth/logout", headers=cabecalho).status_code == 204
    assert client.get("/v1/me", headers=cabecalho).status_code == 401


def test_segundo_login_devolve_o_nome_ja_guardado(client, runtime):
    primeiro = login(client, runtime, PHONE, "passenger", name="Ana Lima")
    codigo = _pedir_codigo(client, runtime)
    corpo = client.post(
        "/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger", "device": "Outro"}
    ).json()
    assert corpo["user_id"] == primeiro.user_id and corpo["is_new_user"] is False and corpo["name"] == "Ana Lima"


def test_codigo_errado_conta_tentativa_mesmo_com_erro_e_cinco_erros_travam(client, runtime):
    # O erro volta como 401, mas a contagem de tentativas precisa ficar gravada (a unidade faz commit).
    certo = _pedir_codigo(client, runtime)
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):
        resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": errado, "role": "passenger"})
        assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "code_invalid"
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": certo, "role": "passenger"})
    assert resposta.status_code == 401 and "tentativas" in resposta.json()["error"]["message"]


def test_celular_invalido_e_papel_invalido_sao_recusados(client):
    resposta = client.post("/v1/auth/code", json={"phone": "12345"})
    assert resposta.status_code == 422 and resposta.json()["error"]["code"] == "invalid"
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": "123456", "role": "chefe"})
    assert resposta.status_code == 422 and resposta.json()["error"]["fields"] == ["role"]


def test_pedir_codigo_demais_para_o_mesmo_numero_da_429(client, runtime):
    for _ in range(5):
        assert client.post("/v1/auth/code", json={"phone": PHONE}).status_code == 204
    resposta = client.post("/v1/auth/code", json={"phone": PHONE})
    assert resposta.status_code == 429 and resposta.json()["error"]["code"] == "too_many_requests"


def test_pedir_codigo_demais_do_mesmo_aparelho_para_numeros_diferentes_da_429(client, runtime, session):
    save_config(session, "auth", AuthConfig(otp_requests_per_ip_hour=3))
    for n in range(3):
        assert client.post("/v1/auth/code", json={"phone": f"75 99999-000{n}"}).status_code == 204
    resposta = client.post("/v1/auth/code", json={"phone": "75 99999-0009"})
    assert resposta.status_code == 429


@pytest.mark.parametrize("cabecalho", [None, "", "Bearer", "Bearer    ", "Basic abc", "Bearer token-inventado"])
def test_sem_token_ou_com_token_ruim_e_401(client, cabecalho):
    headers = {} if cabecalho is None else {"Authorization": cabecalho}
    resposta = client.get("/v1/me", headers=headers)
    assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "unauthorized"


def test_conta_bloqueada_perde_o_acesso_na_hora(client, runtime, session):
    entrou = login(client, runtime, PHONE, "passenger")
    session.get(UserRow, entrou.user_id).is_blocked = True
    session.flush()
    assert client.get("/v1/me", headers=entrou.headers).status_code == 401


def test_sessao_vencida_e_401(client, runtime, session, clock):
    entrou = login(client, runtime, PHONE, "passenger")
    clock.advance(181 * 86400)
    assert client.get("/v1/me", headers=entrou.headers).status_code == 401
    assert session.query(SessionRow).count() == 1


def test_cada_papel_so_entra_nas_rotas_do_seu_papel(client, runtime):
    client.app.add_api_route("/t/passageiro", lambda u=Depends(passenger_user): {"ok": u.role}, methods=["GET"])
    client.app.add_api_route("/t/motoqueiro", lambda u=Depends(rider_user): {"ok": u.role}, methods=["GET"])
    client.app.add_api_route("/t/admin", lambda u=Depends(admin_user): {"ok": u.role}, methods=["GET"])
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    motoqueiro = login(client, runtime, "75 99999-0002", "rider")
    assert client.get("/t/passageiro", headers=passageiro.headers).json() == {"ok": "passenger"}
    assert client.get("/t/motoqueiro", headers=motoqueiro.headers).json() == {"ok": "rider"}
    for rota, quem in (("/t/motoqueiro", passageiro), ("/t/passageiro", motoqueiro), ("/t/admin", passageiro)):
        resposta = client.get(rota, headers=quem.headers)
        assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "wrong_role"


def test_administrador_entra_so_se_ja_existir(client, runtime, session):
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "admin"})
    assert resposta.status_code == 401 and "administrador" in resposta.json()["error"]["message"]
    repo.add_user(session, user_id="adm-1", phone="+5575999991234", name="Levy", role="admin")
    entrou = login(client, runtime, PHONE, "admin")
    assert client.get("/v1/me", headers=entrou.headers).json()["role"] == "admin"


def test_numero_de_motoqueiro_nao_entra_como_passageiro(client, runtime):
    login(client, runtime, PHONE, "rider")
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger"})
    assert resposta.status_code == 401 and "motoqueiro" in resposta.json()["error"]["message"]


def test_nome_curto_demais_e_recusado(client, runtime):
    entrou = login(client, runtime, PHONE, "passenger")
    resposta = client.put("/v1/me", json={"name": " "}, headers=entrou.headers)
    assert resposta.status_code == 422 and "nome" in resposta.json()["error"]["message"]
