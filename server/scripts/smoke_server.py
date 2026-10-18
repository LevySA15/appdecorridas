"""Sobe o servidor de verdade (uvicorn) num esquema temporário do banco e confere o caminho completo de um app:
saúde, login, WebSocket, preço e uma volta do agendador.

Uso (a partir de `server/`):  PYTHONPATH=. .venv/bin/python scripts/smoke_server.py

Usa o PostgreSQL e o Redis de desenvolvimento, mas só o esquema `t_...` criado aqui (apagado no fim) e o banco
número 14 do Redis (esvaziado no fim). Sai com código diferente de zero se algo falhar.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx2 as httpx
import websockets

from simulator.sandbox import Sandbox


def main() -> int:
    with Sandbox() as box:
        client = httpx.Client(base_url=box.url, timeout=5)
        assert client.get("/health").json() == {"status": "ok"}
        print("OK saúde: banco e Redis respondem")

        phone = "75 99999-0001"
        assert client.post("/v1/auth/code", json={"phone": phone}).status_code == 204
        code = client.get("/v1/dev/otp", params={"phone": phone}).json()["code"]
        login = client.post("/v1/auth/verify", json={"phone": phone, "code": code, "role": "passenger"}).json()
        headers = {"Authorization": f"Bearer {login['token']}"}
        assert client.put("/v1/me", json={"name": "Ana Lima"}, headers=headers).json()["name"] == "Ana Lima"
        print("OK login por código e nome")

        ws_url = box.url.replace("http", "ws", 1) + "/v1/ws"

        async def websocket_flow() -> None:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"token": login["token"]}))
                assert json.loads(await ws.recv())["type"] == "ready"
                await ws.send("ping")
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"token": "inventado"}))
                try:
                    await asyncio.wait_for(ws.recv(), 3)
                except websockets.ConnectionClosed as closed:
                    assert closed.rcvd.code == 4401
                else:
                    raise AssertionError("token ruim deveria fechar a conexão")

        asyncio.run(websocket_flow())
        print("OK WebSocket: token bom conecta, token ruim fecha com 4401")

        quote_body = {
            "pickup": {"lat": -12.9644, "lng": -39.2597, "text": "A"},
            "destination": {"lat": -12.95, "lng": -39.25, "text": "B"},
        }
        price = client.post("/v1/passenger/quotes", json=quote_body, headers=headers).json()
        assert price["price_cents"] > 0 and "cash" in price["payment_methods"]
        print(f"OK preço: R$ {price['price_cents'] / 100:.2f}")

        time.sleep(4)          # deixa o agendador dar pelo menos uma volta
        assert box.process.poll() is None, "o servidor caiu"
        problems = box.problems()
    assert not problems, "erros no registro do servidor:\n" + "\n".join(problems)
    print("OK agendador rodou sem erros no registro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
