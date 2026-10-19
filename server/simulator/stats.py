"""O que a simulação foi anotando: chamadas, tempos, avisos e o caminho de cada corrida."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

MAX_EXAMPLES = 40         # exemplos guardados de respostas inesperadas (o total é contado à parte)


def percentile(values: list[float], q: float) -> float | None:
    """Percentil pela posição (o menor valor que cobre `q` da lista). `None` se a lista está vazia."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


@dataclass
class RideRecord:
    ride_id: str
    passenger: int
    method: str
    price_cents: int
    reason: str
    requested_at: float
    accepted_at: float | None = None
    arrived_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    outcome: str | None = None          # completed, cancelled, no_rider, pix_expired, arrival_wait, queue_released...
    queued: bool = False
    missing_events: list[str] = field(default_factory=list)


class Stats:
    def __init__(self) -> None:
        self.calls: Counter[tuple[str, str, int]] = Counter()
        self.latency: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.unexpected: list[str] = []
        self.unexpected_total = 0
        self.events: Counter[str] = Counter()          # avisos do WebSocket recebidos, por tipo
        self.closes: Counter[str] = Counter()          # como as conexões em tempo real terminaram
        self.notes: Counter[str] = Counter()           # coisas que as pessoas fizeram (ou que aconteceram com elas)
        self.rides: dict[str, RideRecord] = {}
        self.price_reasons: Counter[str] = Counter()
        # taxa de cancelamento tardio: cobradas, centavos, do_saldo, retidas, pendentes, pagas_depois,
        # recursos_pedidos, recursos_aceitos, recursos_recusados, recargas
        self.fees: Counter[str] = Counter()

    def record_call(self, method: str, template: str, status: int, seconds: float) -> None:
        self.calls[(method, template, status)] += 1
        self.latency[(method, template)].append(seconds)

    def flag(self, text: str) -> None:
        """Uma resposta que o servidor não devia ter dado."""
        self.unexpected_total += 1
        if len(self.unexpected) < MAX_EXAMPLES:
            self.unexpected.append(text)

    def note(self, key: str, amount: int = 1) -> None:
        self.notes[key] += amount
