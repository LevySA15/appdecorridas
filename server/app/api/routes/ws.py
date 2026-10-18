"""Avisos em tempo real por WebSocket.

O app abre a conexão, manda `{"token": "..."}` como primeira mensagem (o token não vai na URL, que fica
nos registros) e passa a receber `{"type", "data", "at"}`. Os avisos são dicas: ao reconectar, o app
pede o estado de novo (`/v1/passenger/state` ou `/v1/rider/state`), que é a fonte da verdade.
"""
from __future__ import annotations

import asyncio

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.realtime.hub import Connection

router = APIRouter(tags=["tempo real"])

AUTH_TIMEOUT_S = 10.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_RESYNC = 4408         # a fila encheu: reconecte e peça o estado


async def pump(websocket, connection: Connection) -> None:
    """Entrega à tela o que chega na fila. Termina quando a tela sai, a fila encheu ou o envio falha."""
    async with anyio.create_task_group() as group:

        async def reader() -> None:
            while True:                    # o app manda "ping" de vez em quando; o conteúdo não importa
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    group.cancel_scope.cancel()
                    return

        group.start_soon(reader)
        try:
            while True:
                if connection.overflowed:
                    await websocket.close(code=CLOSE_RESYNC)
                    break
                message = await connection.queue.get()
                if connection.overflowed:
                    await websocket.close(code=CLOSE_RESYNC)
                    break
                await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):     # a tela saiu no meio do envio
            pass
        group.cancel_scope.cancel()


@router.websocket("/v1/ws")
async def events_socket(websocket: WebSocket) -> None:
    runtime = websocket.app.state.runtime
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_S)
        token = first["token"] if isinstance(first, dict) else None
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError):
        token = None
    user = None
    if isinstance(token, str) and token:
        user = await run_in_threadpool(
            runtime.run, lambda unit: unit.auth.authenticate(unit.session, token, unit.now)
        )
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    connection = Connection(user.user_id, asyncio.get_running_loop())
    runtime.hub.add(connection)
    try:
        await websocket.send_json(
            {"type": "ready", "data": {"user_id": user.user_id, "role": user.role}, "at": runtime.clock()}
        )
        await pump(websocket, connection)
    finally:
        runtime.hub.remove(connection)
