import asyncio
import json
import os

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import simulator.runner as runner
from simulator.api import Api
from simulator.behavior import Profile
from simulator.model import SimConfig
from simulator.population import gather_all
from simulator.runner import simulate
from simulator.stats import Stats
from simulator.world import SimulationError, World


def app_do_pix() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/dev/pix/{charge_id}/pay")
    def pagar(charge_id: str):
        if charge_id == "ch-fantasma":
            return JSONResponse({"error": {"code": "not_found", "message": "?"}}, status_code=404)
        return {"status": {"ch-1": "applied", "ch-2": "refunded", "ch-3": "duplicate"}[charge_id]}

    return app


def test_pagar_pix_so_aceita_applied_ou_refunded_e_cobranca_desconhecida_e_alarme():
    stats = Stats()
    api = Api("http://teste", stats, transport=httpx.ASGITransport(app=app_do_pix()))
    mundo = World(api, stats, Profile(), "ws://x/v1/ws", 1)

    async def caso():
        for cobranca in ("ch-1", "ch-2"):            # pago, ou pago depois de a corrida ser cancelada (devolvido)
            await mundo.pay_pix(cobranca)
        assert stats.unexpected_total == 0
        await mundo.pay_pix("ch-3")                  # o servidor diz que já tinha tratado este aviso
        await mundo.pay_pix("ch-fantasma")

    asyncio.run(caso())
    assert stats.unexpected_total == 2 and "ch-3" in stats.unexpected[0] and "duplicate" in stats.unexpected[0]


def test_gather_all_espera_todos_terminarem_e_depois_levanta_o_primeiro_erro():
    feitos = []

    async def bom():
        await asyncio.sleep(0.05)
        feitos.append("bom")

    async def ruim():
        raise SimulationError("falhou")

    async def caso():
        with pytest.raises(SimulationError, match="falhou"):
            await gather_all([ruim(), bom()])

    asyncio.run(caso())
    assert feitos == ["bom"]                         # quem estava no meio de um login terminou antes do erro subir


def test_tokens_de_quem_ja_entrou_ficam_guardados_mesmo_se_o_cadastro_falha(monkeypatch, tmp_path):
    async def prepara_e_falha(world, cache, admin_phone, riders, passengers, today=None):
        cache.put("75 98200-0001", "token-1", "u1")
        raise SimulationError("cadastro recusado")

    monkeypatch.setattr(runner, "prepare", prepara_e_falha)
    cfg = SimConfig(url="http://127.0.0.1:1", admin_phone="75 99999-0000", state_dir=tmp_path)
    with pytest.raises(SimulationError, match="recusado"):
        asyncio.run(simulate(cfg))
    arquivo = tmp_path / "pessoas.json"
    assert json.loads(arquivo.read_text())["http://127.0.0.1:1"]["75 98200-0001"]["token"] == "token-1"
    assert os.stat(arquivo).st_mode & 0o777 == 0o600
