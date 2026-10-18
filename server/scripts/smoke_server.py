"""Sobe o servidor de verdade (uvicorn) num esquema temporário do banco e confere o caminho completo de um app:
saúde, login, WebSocket, preço e uma volta do agendador.

Uso (a partir de `server/`):  PYTHONPATH=. .venv/bin/python scripts/smoke_server.py

Usa o PostgreSQL e o Redis de desenvolvimento, mas só o esquema `t_...` criado aqui (apagado no fim) e o banco
número 14 do Redis (esvaziado no fim). Sai com código diferente de zero se algo falhar.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote

import httpx2 as httpx
import redis
import websockets
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.settings import load_settings


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    settings = load_settings()
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema},public"})
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        cfg.attributes["schema"] = schema
        command.upgrade(cfg, "head")
    engine.dispose()

    port, uploads = free_port(), tempfile.mkdtemp(prefix="smoke-uploads-")
    redis_url = settings.redis_url.rsplit("/", 1)[0] + "/14"
    separator = "&" if "?" in settings.database_url else "?"
    env = dict(
        os.environ,
        DATABASE_URL=settings.database_url + separator + "options=" + quote(f"-csearch_path={schema},public"),
        REDIS_URL=redis_url, APP_MODE="dev", WEBHOOK_SECRET="segredo-do-smoke", UPLOAD_DIR=uploads,
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", "app.main:create_default_app", "--port", str(port),
         "--log-level", "warning"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.25)
        else:
            raise SystemExit("o servidor não subiu")
        client = httpx.Client(base_url=base, timeout=5)
        assert client.get("/health").json() == {"status": "ok"}
        print("OK saúde: banco e Redis respondem")

        phone = "75 99999-0001"
        assert client.post("/v1/auth/code", json={"phone": phone}).status_code == 204
        code = client.get("/v1/dev/otp", params={"phone": phone}).json()["code"]
        login = client.post("/v1/auth/verify", json={"phone": phone, "code": code, "role": "passenger"}).json()
        headers = {"Authorization": f"Bearer {login['token']}"}
        assert client.put("/v1/me", json={"name": "Ana Lima"}, headers=headers).json()["name"] == "Ana Lima"
        print("OK login por código e nome")

        async def websocket_flow() -> None:
            async with websockets.connect(f"ws://127.0.0.1:{port}/v1/ws") as ws:
                await ws.send(json.dumps({"token": login["token"]}))
                assert json.loads(await ws.recv())["type"] == "ready"
                await ws.send("ping")
            async with websockets.connect(f"ws://127.0.0.1:{port}/v1/ws") as ws:
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
        assert server.poll() is None, "o servidor caiu"
    finally:
        server.terminate()
        output = server.communicate(timeout=10)[0]
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        shutil.rmtree(uploads, ignore_errors=True)
        redis.Redis.from_url(redis_url).flushdb()
    bad = [line for line in output.splitlines() if "Traceback" in line or "ERROR" in line]
    assert not bad, "erros no registro do servidor:\n" + "\n".join(bad)
    print("OK agendador rodou sem erros no registro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
