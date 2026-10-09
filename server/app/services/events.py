"""Avisos para os apps. Os serviços só anotam; quem chama publica depois do commit (plano 2C)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    user_id: str
    type: str
    payload: dict = field(default_factory=dict)


class EventCollector:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def add(self, user_id: str, type: str, payload: dict | None = None) -> None:
        self._events.append(Event(user_id, type, payload or {}))

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def drain(self) -> list[Event]:
        events, self._events = self._events, []
        return events
