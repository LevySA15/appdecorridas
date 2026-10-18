"""Conexão em tempo real de uma pessoa (WebSocket), como o app faria: entra com o token, guarda os avisos e reconecta.

Os avisos são dicas. Quem usa o `Feed` relê o estado pela API quando `resync` está ligado (conectou de novo) ou quando
chega aviso; o aviso sozinho nunca é a verdade.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict

import websockets

from simulator.stats import Stats


class Feed:
    def __init__(self, ws_url: str, token: str, stats: Stats, *, retry_s: float = 0.5) -> None:
        self.ws_url = ws_url
        self.token = token
        self.stats = stats
        self.retry_s = retry_s
        self.generation = 0                 # sobe a cada conexão nova; se mudou, algum aviso pode ter se perdido
        self.resync = False                 # ligado quando acabou de conectar: leia o estado de novo
        self.seen: dict[str, set[str]] = defaultdict(set)      # corrida -> tipos de aviso recebidos
        self.latest: dict[tuple[str, str], dict] = {}          # (corrida, tipo) -> dados do último aviso desse tipo
        self._inbox: list[dict] = []
        self._wake = asyncio.Event()
        self._ws = None
        self._closing = False

    def take(self) -> list[dict]:
        taken, self._inbox = self._inbox, []
        return taken

    async def wait(self, timeout: float) -> None:
        """Dorme até chegar aviso, conectar ou passar `timeout`."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    def _receive(self, message: dict) -> None:
        kind = message.get("type", "?")
        self.stats.events[kind] += 1
        ride_id = (message.get("data") or {}).get("ride_id")
        if ride_id:
            self.seen[ride_id].add(kind)
            self.latest[(ride_id, kind)] = message["data"]
        self._inbox.append(message)
        self._wake.set()

    async def run(self) -> None:
        while not self._closing:
            try:
                async with websockets.connect(self.ws_url, open_timeout=10) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"token": self.token}))
                    ready = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if ready.get("type") != "ready":
                        raise ConnectionError(f"resposta inesperada: {ready.get('type')}")
                    self.generation += 1
                    self.resync = True
                    self._wake.set()
                    async for raw in ws:
                        self._receive(json.loads(raw))
                self.stats.closes["fechada"] += 1
            except websockets.ConnectionClosed as closed:
                code = closed.rcvd.code if closed.rcvd else 0
                self.stats.closes[str(code)] += 1
                if code == 4401:
                    self.stats.flag("WebSocket: o servidor recusou o token (4401)")
            except (OSError, asyncio.TimeoutError, ConnectionError, websockets.WebSocketException) as exc:
                self.stats.closes[type(exc).__name__] += 1
            finally:
                self._ws = None
            if not self._closing:
                await asyncio.sleep(self.retry_s)

    async def drop(self) -> None:
        """Derruba a conexão de propósito (o celular perdeu o sinal); o laço reconecta sozinho."""
        if self._ws is not None:
            await self._ws.close()

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        if self._ws is not None:
            await self._ws.close()
