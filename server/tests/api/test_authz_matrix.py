"""Quem pode chamar o quê, conferido em TODAS as rotas da API de uma vez (a lista vem do OpenAPI do próprio servidor).

Rota nova que não cabe em nenhuma regra abaixo reprova o teste: quem cria a rota decide, aqui, quem pode usá-la.
"""
import re

import pytest

from app.db import repositories as repo
from tests.api.helpers import login, online_rider, rider_phone

ID_QUALQUER = "00000000-0000-0000-0000-000000000000"

# Abertas de propósito: o login (não há token ainda) e o aviso do provedor (assinado, não tem token).
PUBLICAS = {("GET", "/health"), ("POST", "/v1/auth/code"), ("POST", "/v1/auth/verify"), ("POST", "/v1/webhooks/pix")}
# Cada prefixo é de um papel só.
POR_PREFIXO = {"/v1/admin/": "admin", "/v1/passenger/": "passenger", "/v1/rider/": "rider"}
# Servem a mais de um papel, mas sempre com login (as regras finas estão nos testes de cada rota).
COM_LOGIN_QUALQUER_PAPEL = {
    ("GET", "/v1/me"), ("PUT", "/v1/me"), ("POST", "/v1/auth/logout"), ("GET", "/v1/charges/{charge_id}"),
    ("GET", "/v1/riders/{rider_id}/documents/{kind}"), ("POST", "/v1/rides/{ride_id}/rating"),
    ("POST", "/v1/rides/{ride_id}/safety/{alert_id}/ok"), ("POST", "/v1/rides/{ride_id}/sos"),
}


def _rotas(client):
    achadas = []
    for caminho, metodos in client.app.openapi()["paths"].items():
        for metodo in metodos:
            if metodo.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                achadas.append((metodo.upper(), caminho))
    return sorted(achadas)


def _preenche(caminho: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "selfie" if m.group(1) == "kind" else ID_QUALQUER, caminho)


def _chama(client, metodo, caminho, headers=None):
    return client.request(metodo, _preenche(caminho), headers=headers or {}, json={} if metodo != "GET" else None)


def _papel_da_rota(metodo, caminho):
    for prefixo, papel in POR_PREFIXO.items():
        if caminho.startswith(prefixo):
            return papel
    return None


@pytest.fixture()
def pessoas(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    return {
        "passenger": login(client, runtime, "75 99999-0001", "passenger", name="Ana"),
        "rider": login(client, runtime, rider_phone(1), "rider"),
        "admin": login(client, runtime, "75 99999-0000", "admin"),
    }


def test_toda_rota_tem_regra_de_acesso(client):
    sem_regra = [
        (m, c) for m, c in _rotas(client)
        if (m, c) not in PUBLICAS and (m, c) not in COM_LOGIN_QUALQUER_PAPEL and _papel_da_rota(m, c) is None
        and not c.startswith("/v1/dev/")
    ]
    assert sem_regra == [], f"rota nova sem regra de acesso em test_authz_matrix.py: {sem_regra}"


def test_sem_token_ou_com_token_falso_toda_rota_protegida_responde_401(client):
    protegidas = [(m, c) for m, c in _rotas(client) if (m, c) not in PUBLICAS and not c.startswith("/v1/dev/")]
    assert len(protegidas) > 40
    for metodo, caminho in protegidas:
        for headers in ({}, {"Authorization": "Bearer token-que-nao-existe"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}):
            resposta = _chama(client, metodo, caminho, headers)
            assert resposta.status_code == 401, f"{metodo} {caminho} com {headers} deu {resposta.status_code}: {resposta.text[:120]}"


@pytest.mark.parametrize("papel", ["passenger", "rider", "admin"])
def test_rota_de_um_papel_recusa_os_outros_com_403(client, pessoas, papel):
    checadas = 0
    for metodo, caminho in _rotas(client):
        dono = _papel_da_rota(metodo, caminho)
        if dono is None or dono == papel:
            continue
        resposta = _chama(client, metodo, caminho, pessoas[papel].headers)
        assert resposta.status_code == 403, f"{papel} em {metodo} {caminho} deu {resposta.status_code}: {resposta.text[:120]}"
        assert resposta.json()["error"]["code"] == "wrong_role"
        checadas += 1
    assert checadas >= 20


def test_o_aviso_do_provedor_sem_assinatura_e_recusado(client):
    for headers in ({}, {"X-Signature": "falsa"}, {"X-Webhook-Signature": "falsa"}):
        resposta = client.post("/v1/webhooks/pix", content=b'{"event":"charge.paid","charge_id":"x"}', headers=headers)
        assert resposta.status_code in (400, 401, 403), resposta.text


def test_token_apos_logout_deixa_de_valer(client, pessoas):
    token = pessoas["passenger"]
    assert client.get("/v1/me", headers=token.headers).status_code == 200
    assert client.post("/v1/auth/logout", headers=token.headers).status_code == 204
    assert client.get("/v1/me", headers=token.headers).status_code == 401
    assert client.get("/v1/passenger/state", headers=token.headers).status_code == 401
