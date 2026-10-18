import asyncio
import json

from websockets.asyncio.server import serve

from simulator.feed import Feed
from simulator.stats import Stats


async def servidor_de_mentira(comportamento):
    """Sobe um servidor WebSocket local que se comporta como `comportamento(ws, conexao_numero)` manda."""
    conexoes = {"n": 0}

    async def handler(ws):
        conexoes["n"] += 1
        primeira = json.loads(await ws.recv())
        if primeira.get("token") != "bom":
            await ws.close(4401)
            return
        await ws.send(json.dumps({"type": "ready", "data": {}, "at": 0}))
        await comportamento(ws, conexoes["n"])

    server = await serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://127.0.0.1:{port}/v1/ws", conexoes


async def esperar(condicao, tempo=5.0):
    for _ in range(int(tempo / 0.02)):
        if condicao():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("não aconteceu a tempo")


def test_conecta_recebe_os_avisos_e_pede_para_reler_o_estado():
    async def caso():
        async def manda_um_aviso(ws, n):
            await ws.send(json.dumps({"type": "offer", "data": {"ride_id": "r1"}, "at": 1}))
            await ws.wait_closed()

        server, url, _ = await servidor_de_mentira(manda_um_aviso)
        stats = Stats()
        feed = Feed(url, "bom", stats)
        tarefa = asyncio.create_task(feed.run())
        await feed.wait(3)
        assert feed.resync is True and feed.generation == 1
        assert [m["type"] for m in feed.take()] == ["offer"] and feed.take() == []
        assert feed.seen["r1"] == {"offer"} and stats.events["offer"] == 1
        await feed.close()
        await tarefa
        server.close()

    asyncio.run(caso())


def test_token_recusado_fecha_com_4401_e_e_denunciado():
    async def caso():
        async def nada(ws, n):
            await ws.wait_closed()

        server, url, _ = await servidor_de_mentira(nada)
        stats = Stats()
        feed = Feed(url, "ruim", stats, retry_s=0.05)
        tarefa = asyncio.create_task(feed.run())
        await esperar(lambda: stats.closes["4401"] >= 1)
        await feed.close()
        await tarefa
        assert stats.unexpected_total >= 1 and "4401" in stats.unexpected[0] and feed.generation == 0
        server.close()

    asyncio.run(caso())


def test_derrubar_de_proposito_reconecta_e_pede_o_estado_de_novo():
    async def caso():
        async def segura(ws, n):
            await ws.wait_closed()

        server, url, conexoes = await servidor_de_mentira(segura)
        stats = Stats()
        feed = Feed(url, "bom", stats, retry_s=0.05)
        tarefa = asyncio.create_task(feed.run())
        await feed.wait(3)
        feed.resync = False
        await feed.drop()
        await esperar(lambda: feed.generation == 2)
        assert feed.resync is True and conexoes["n"] == 2 and stats.unexpected_total == 0
        await feed.close()
        await tarefa
        server.close()

    asyncio.run(caso())


def test_servidor_que_fecha_com_4408_faz_reconectar():
    async def caso():
        async def fecha_na_primeira(ws, n):
            if n == 1:
                await ws.close(4408)
            else:
                await ws.wait_closed()

        server, url, _ = await servidor_de_mentira(fecha_na_primeira)
        stats = Stats()
        feed = Feed(url, "bom", stats, retry_s=0.05)
        tarefa = asyncio.create_task(feed.run())
        await esperar(lambda: feed.generation == 2)
        assert stats.closes["4408"] == 1 and stats.unexpected_total == 0
        await feed.close()
        await tarefa
        server.close()

    asyncio.run(caso())


def test_fechar_enquanto_a_conexao_ainda_abre_nao_deixa_o_laco_preso():
    async def caso():
        async def devagar(connection, request):
            await asyncio.sleep(0.5)             # o servidor demora a aceitar a conexão

        async def handler(ws):
            await ws.recv()
            await ws.send(json.dumps({"type": "ready", "data": {}, "at": 0}))
            await ws.wait_closed()

        server = await serve(handler, "127.0.0.1", 0, process_request=devagar)
        port = server.sockets[0].getsockname()[1]
        feed = Feed(f"ws://127.0.0.1:{port}/v1/ws", "bom", Stats())
        tarefa = asyncio.create_task(feed.run())
        await asyncio.sleep(0.15)                # a conexão ainda está abrindo: não há o que fechar
        await feed.close()
        await asyncio.wait_for(tarefa, 3)        # tem de terminar sozinho assim que a conexão abrir
        server.close()

    asyncio.run(caso())


def test_parar_o_feed_espera_pouco_e_cancela_o_laco_que_nao_obedece():
    async def caso():
        feed = Feed("ws://127.0.0.1:1/v1/ws", "bom", Stats())
        teimoso = asyncio.create_task(asyncio.sleep(60))
        await asyncio.wait_for(feed.stop(teimoso, grace_s=0.2), 2)
        assert teimoso.cancelled()

    asyncio.run(caso())
