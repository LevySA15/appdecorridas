"""CORS só no modo de desenvolvimento: deixa o app aberto no navegador (Chrome, `localhost:<porta>`) falar com o
servidor de desenvolvimento. Servidor público (`DEV_ROUTES=off`) não responde a CORS de ninguém."""
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app

PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


@pytest.mark.parametrize("origem", ["http://localhost:8081", "http://127.0.0.1:8082"])
def test_em_desenvolvimento_o_localhost_pode_chamar_a_api(runtime, origem):
    runtime.dev_routes = True
    with TestClient(create_app(runtime)) as c:
        resposta = c.options("/v1/auth/code", headers={"Origin": origem, **PREFLIGHT})
        assert resposta.status_code == 200
        assert resposta.headers["access-control-allow-origin"] == origem
        assert "authorization" in resposta.headers["access-control-allow-headers"].lower()
        assert c.get("/health", headers={"Origin": origem}).headers["access-control-allow-origin"] == origem


@pytest.mark.parametrize("origem", ["https://site-de-terceiro.com", "http://localhost.evil.com", "http://evil.com:8081"])
def test_em_desenvolvimento_outros_enderecos_nao_passam(runtime, origem):
    runtime.dev_routes = True
    with TestClient(create_app(runtime)) as c:
        resposta = c.options("/v1/auth/code", headers={"Origin": origem, **PREFLIGHT})
        assert "access-control-allow-origin" not in resposta.headers
        assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": origem}).headers


def test_com_o_interruptor_desligado_nem_o_localhost_passa(runtime):
    runtime.dev_routes = False
    with TestClient(create_app(runtime)) as c:
        resposta = c.options("/v1/auth/code", headers={"Origin": "http://localhost:8081", **PREFLIGHT})
        assert "access-control-allow-origin" not in resposta.headers
        assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "http://localhost:8081"}).headers
