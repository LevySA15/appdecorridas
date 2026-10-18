import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routes import ws as ws_module
from app.db.models import UserRow
from app.realtime.hub import Connection
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt

_pool = ThreadPoolExecutor(max_workers=4)


def receber(ws, segundos=3.0):
    """`receive_json` sem ficar preso para sempre se o aviso não vier."""
    return _pool.submit(ws.receive_json).result(timeout=segundos)


@contextmanager
def conectado(client, quem):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": quem.token})
        assert receber(ws)["type"] == "ready"
        yield ws


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def test_conexao_autorizada_recebe_o_pronto_com_quem_e(client, pax, runtime):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": pax.token})
        pronto = receber(ws)
    assert pronto == {"type": "ready", "data": {"user_id": pax.user_id, "role": "passenger"}, "at": runtime.clock()}


def test_os_avisos_chegam_so_a_quem_e_deles_depois_do_commit(client, pax, rider):
    with conectado(client, pax) as ws_pax, conectado(client, rider) as ws_rider:
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
        pedido = client.post(
            "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
        ).json()
        oferta = receber(ws_rider)
        assert oferta["type"] == "offer" and oferta["data"]["ride_id"] == pedido["ride_id"]
        client.post(f"/v1/rider/offers/{pedido['ride_id']}/accept", headers=rider.headers)
        aceito = receber(ws_pax)
        assert aceito["type"] == "rider_accepted" and aceito["data"]["pin"] == pedido["pin"]
        assert receber(ws_rider)["type"] == "ride_assigned"


def test_duas_telas_do_mesmo_usuario_recebem_o_mesmo_aviso(client, pax, rider, runtime):
    with conectado(client, rider) as primeira, conectado(client, rider) as segunda:
        assert runtime.hub.count() == 2
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
        client.post("/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers)
        assert receber(primeira)["type"] == "offer" and receber(segunda)["type"] == "offer"


def test_sair_tira_a_conexao_do_hub(client, pax, runtime):
    with conectado(client, pax):
        assert runtime.hub.count() == 1
    assert runtime.hub.count() == 0


@pytest.mark.parametrize("primeira", [{"token": "inventado"}, {"token": 123}, {"oi": 1}, [], "texto"])
def test_primeira_mensagem_ruim_fecha_com_4401(client, primeira):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json(primeira)
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_primeira_mensagem_que_nao_e_json_fecha_com_4401(client):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_text("isto não é json")
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_quem_nao_se_identifica_a_tempo_e_desconectado(client, monkeypatch):
    monkeypatch.setattr(ws_module, "AUTH_TIMEOUT_S", 0.2)
    with client.websocket_connect("/v1/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_conta_bloqueada_ou_sessao_encerrada_nao_conecta(client, pax, rider, session):
    client.post("/v1/auth/logout", headers=pax.headers)
    session.get(UserRow, rider.user_id).is_blocked = True
    session.flush()
    for quem in (pax, rider):
        with client.websocket_connect("/v1/ws") as ws:
            ws.send_json({"token": quem.token})
            with pytest.raises(WebSocketDisconnect) as erro:
                receber(ws)
        assert erro.value.code == 4401


def test_o_cliente_pode_mandar_ping_de_texto_sem_derrubar_a_conexao(client, pax):
    with conectado(client, pax) as ws:
        ws.send_text("ping")
        ws.send_bytes(b"\x00")
        ws.send_text("ping")
        resposta = client.get("/v1/me", headers=pax.headers)
        assert resposta.status_code == 200


# --- a bomba que entrega a fila à tela, testada sem rede ------------------------------------------


class TelaFalsa:
    def __init__(self, depois_de=None):
        self.enviados, self.fechou_com = [], None
        self.saiu = asyncio.Event()

    async def receive(self):
        await self.saiu.wait()
        return {"type": "websocket.disconnect"}

    async def send_json(self, message):
        self.enviados.append(message)

    async def close(self, code=1000):
        self.fechou_com = code


def test_bomba_entrega_na_ordem_e_termina_quando_a_tela_sai():
    async def main():
        tela, conexao = TelaFalsa(), Connection("u1", asyncio.get_running_loop())
        tarefa = asyncio.create_task(ws_module.pump(tela, conexao))
        conexao.deliver({"i": 1})
        conexao.deliver({"i": 2})
        for _ in range(20):
            await asyncio.sleep(0.01)
        tela.saiu.set()
        await asyncio.wait_for(tarefa, 1)
        return tela.enviados, tela.fechou_com

    assert asyncio.run(main()) == ([{"i": 1}, {"i": 2}], None)


def test_bomba_fecha_a_conexao_com_fila_cheia_para_o_app_pedir_o_estado_de_novo():
    async def main():
        tela, conexao = TelaFalsa(), Connection("u1", asyncio.get_running_loop(), max_queue=1)
        conexao.deliver({"i": 1})
        conexao.deliver({"i": 2})
        await asyncio.sleep(0.01)
        await asyncio.wait_for(ws_module.pump(tela, conexao), 1)
        return tela.enviados, tela.fechou_com

    assert asyncio.run(main()) == ([], 4408)
