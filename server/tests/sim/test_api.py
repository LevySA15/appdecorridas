import asyncio

import httpx2 as httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from simulator.api import Api
from simulator.stats import Stats, percentile


def app_de_mentira() -> FastAPI:
    app = FastAPI()

    @app.get("/v1/ok/{item}")
    def ok(item: str):
        return {"item": item}

    @app.post("/v1/gone")
    def gone():
        return JSONResponse({"error": {"code": "offer_gone", "message": "Já foi."}}, status_code=409)

    @app.post("/v1/surprise")
    def surprise():
        return JSONResponse({"error": {"code": "invalid", "message": "?"}}, status_code=422)

    @app.get("/v1/boom")
    def boom():
        raise HTTPException(500, "quebrou")

    @app.get("/v1/empty")
    def empty():
        return JSONResponse(None, status_code=204)

    @app.get("/v1/auth")
    def auth(authorization: str = Header("")):
        return {"header": authorization}

    return app


@pytest.fixture()
def api_e_stats():
    stats = Stats()
    return Api("http://teste", stats, transport=httpx.ASGITransport(app=app_de_mentira())), stats


def run(coro):
    return asyncio.run(coro)


def test_resposta_boa_vem_com_o_corpo_e_entra_na_conta_pelo_modelo_da_rota(api_e_stats):
    api, stats = api_e_stats
    reply = run(api.call("GET", "/v1/ok/{item}", params={"item": "abc"}))
    assert reply.ok and reply.status == 200 and reply.body == {"item": "abc"}
    assert stats.calls[("GET", "/v1/ok/{item}", 200)] == 1
    assert len(stats.latency[("GET", "/v1/ok/{item}")]) == 1 and stats.unexpected_total == 0


def test_erro_documentado_e_esperado_so_quando_o_chamador_diz(api_e_stats):
    api, stats = api_e_stats
    reply = run(api.call("POST", "/v1/gone", ok=("offer_gone",)))
    assert not reply.ok and reply.code == "offer_gone" and reply.message == "Já foi."
    assert stats.unexpected_total == 0
    run(api.call("POST", "/v1/gone"))
    assert stats.unexpected_total == 1 and "POST /v1/gone" in stats.unexpected[0] and "offer_gone" in stats.unexpected[0]


def test_erro_de_servidor_e_sempre_inesperado_mesmo_na_lista(api_e_stats):
    api, stats = api_e_stats
    reply = run(api.call("GET", "/v1/boom", ok=("http_500", "internal")))
    assert reply.status == 500 and stats.unexpected_total == 1


def test_corpo_vazio_e_aceito(api_e_stats):
    api, _ = api_e_stats
    reply = run(api.call("GET", "/v1/empty"))
    assert reply.ok and reply.body is None


def test_o_token_vai_no_cabecalho(api_e_stats):
    api, _ = api_e_stats
    assert run(api.call("GET", "/v1/auth", token="abc")).body == {"header": "Bearer abc"}


def test_servidor_fora_do_ar_vira_resposta_zero_e_conta_como_inesperado():
    stats = Stats()
    api = Api("http://127.0.0.1:1", stats, timeout=1)
    reply = run(api.call("GET", "/health"))
    assert reply.status == 0 and not reply.ok and stats.unexpected_total == 1


def test_percentil_por_posicao():
    assert percentile([], 0.5) is None
    assert percentile([5.0], 0.95) == 5.0
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5) == 5
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
