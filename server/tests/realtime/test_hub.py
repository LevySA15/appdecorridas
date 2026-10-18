import asyncio

from app.realtime.hub import Connection, Hub, to_message
from app.services.events import Event


def test_mensagem_tem_tipo_dados_e_hora():
    assert to_message(Event("u1", "offer", {"ride_id": "ride-1"}), 12.5) == {
        "type": "offer", "data": {"ride_id": "ride-1"}, "at": 12.5,
    }


def test_publicar_de_outra_thread_chega_na_fila_da_conexao():
    async def main():
        hub = Hub()
        conn = Connection("u1", asyncio.get_running_loop())
        hub.add(conn)
        entregues = await asyncio.to_thread(hub.publish, "u1", {"type": "a"})   # como um pedido HTTP síncrono
        return entregues, await asyncio.wait_for(conn.queue.get(), 1)

    assert asyncio.run(main()) == (1, {"type": "a"})


def test_quem_nao_esta_conectado_nao_recebe_nada_e_nao_da_erro():
    assert Hub().publish("ninguem", {"type": "a"}) == 0


def test_duas_telas_do_mesmo_usuario_recebem_e_a_removida_nao():
    async def main():
        hub = Hub()
        loop = asyncio.get_running_loop()
        a, b = Connection("u1", loop), Connection("u1", loop)
        hub.add(a)
        hub.add(b)
        hub.remove(a)
        entregues = hub.publish("u1", {"type": "x"})
        await asyncio.sleep(0)
        return entregues, a.queue.qsize(), b.queue.qsize()

    assert asyncio.run(main()) == (1, 0, 1)


def test_publicar_varios_avisos_respeita_o_dono_de_cada_um():
    async def main():
        hub = Hub()
        loop = asyncio.get_running_loop()
        pax, rider = Connection("p1", loop), Connection("r1", loop)
        hub.add(pax)
        hub.add(rider)
        hub.publish_events([Event("p1", "rider_accepted", {}), Event("r1", "ride_assigned", {}), Event("zz", "x")], 5.0)
        await asyncio.sleep(0)
        return (await pax.queue.get())["type"], (await rider.queue.get())["type"]

    assert asyncio.run(main()) == ("rider_accepted", "ride_assigned")


def test_fila_cheia_marca_a_conexao_em_vez_de_perder_aviso_em_silencio():
    # O WebSocket fecha uma conexão marcada; o app reconecta e pede o estado de novo.
    async def main():
        conn = Connection("u1", asyncio.get_running_loop(), max_queue=2)
        for i in range(3):
            conn.deliver({"i": i})
        await asyncio.sleep(0)
        return conn.overflowed, conn.queue.qsize()

    assert asyncio.run(main()) == (True, 2)
