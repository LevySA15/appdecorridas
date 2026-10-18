"""Cadastro e aprovação das pessoas de mentira contra um servidor de verdade."""
import asyncio

from simulator.api import Api
from simulator.behavior import Profile
from simulator.population import prepare
from simulator.sandbox import ADMIN_PHONE
from simulator.stats import Stats
from simulator.world import TokenCache, World


def test_preparar_de_novo_reencontra_as_pessoas_sem_cadastrar_outra_vez(box, tmp_path):
    async def caso():
        stats = Stats()
        api = Api(box.url, stats)
        world = World(api, stats, Profile(), "", 1)
        cache = TokenCache(tmp_path / "pessoas.json", box.url)
        primeira = await prepare(world, cache, ADMIN_PHONE, 2, 2)
        cache.save()
        segunda = await prepare(world, TokenCache(tmp_path / "pessoas.json", box.url), ADMIN_PHONE, 2, 2)
        aprovados = await api.call(
            "GET", "/v1/admin/riders", token=primeira.admin.token, query={"status": "approved"}
        )
        await api.close()
        return primeira, segunda, stats, aprovados.body

    primeira, segunda, stats, aprovados = asyncio.run(caso())
    assert [l.user_id for _, l in segunda.riders] == [l.user_id for _, l in primeira.riders]
    assert [l.user_id for _, l in segunda.passengers] == [l.user_id for _, l in primeira.passengers]
    assert len(aprovados) == 2 and stats.unexpected_total == 0
    assert stats.calls[("POST", "/v1/rider/register", 201)] == 2          # cada motoqueiro se cadastra uma vez só
    assert stats.calls[("POST", "/v1/auth/code", 204)] == 5               # administrador + 4 pessoas, só na primeira vez
