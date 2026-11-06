"""`DEV_ROUTES=off`: servidor público em modo dev não monta as rotas que entregam código de login nem a documentação."""
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app


@pytest.mark.parametrize("caminho", ["/v1/dev/audit", "/v1/dev/otp?phone=75999990000", "/docs", "/openapi.json"])
def test_com_o_interruptor_desligado_as_rotas_de_desenvolvimento_nao_existem(runtime, caminho):
    runtime.dev_routes = False
    with TestClient(create_app(runtime)) as c:
        assert c.get(caminho).status_code == 404
        assert c.get("/health").status_code == 200


def test_com_o_interruptor_ligado_nada_muda(runtime):
    runtime.dev_routes = True
    with TestClient(create_app(runtime)) as c:
        assert c.get("/docs").status_code == 200
        assert c.get("/v1/dev/audit").status_code == 200


def test_por_padrao_fica_ligado(runtime):
    assert runtime.dev_routes is True
