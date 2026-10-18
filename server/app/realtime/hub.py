"""Quem está conectado por WebSocket e como os avisos chegam até essas conexões.

Os serviços rodam em threads comuns (as rotas são síncronas) e o WebSocket vive no laço assíncrono do
servidor. `Connection.deliver` faz a ponte com `call_soon_threadsafe`, então `Hub.publish` pode ser
chamado de qualquer thread. O aviso é uma dica: se a conexão cair ou a fila encher, o app reconecta e
pede o estado de novo (`/state`), que é a fonte da verdade.
"""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from collections.abc import Iterable

from app.services.events import Event


def to_message(event: Event, now: float) -> dict:
    return {"type": event.type, "data": event.payload, "at": now}


class Connection:
    def __init__(self, user_id: str, loop: asyncio.AbstractEventLoop, max_queue: int = 100) -> None:
        self.user_id = user_id
        self.loop = loop
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self.overflowed = False     # a fila encheu: quem lê fecha a conexão para o app pedir o estado de novo

    def _put(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True

    def deliver(self, message: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self._put, message)
        except RuntimeError:        # o laço já fechou: a conexão morreu entre o aviso e a entrega
            pass


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, set[Connection]] = defaultdict(set)

    def add(self, connection: Connection) -> None:
        with self._lock:
            self._connections[connection.user_id].add(connection)

    def remove(self, connection: Connection) -> None:
        with self._lock:
            group = self._connections.get(connection.user_id)
            if group is None:
                return
            group.discard(connection)
            if not group:
                del self._connections[connection.user_id]

    def publish(self, user_id: str, message: dict) -> int:
        """Entrega a todas as conexões do usuário. Devolve quantas receberam."""
        with self._lock:
            targets = list(self._connections.get(user_id, ()))
        for connection in targets:
            connection.deliver(message)
        return len(targets)

    def publish_events(self, events: Iterable[Event], now: float) -> None:
        for event in events:
            self.publish(event.user_id, to_message(event, now))

    def count(self) -> int:
        with self._lock:
            return sum(len(group) for group in self._connections.values())
