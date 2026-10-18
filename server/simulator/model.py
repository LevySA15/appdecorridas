"""O que entra e o que sai de uma rodada da simulação."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from simulator.behavior import Profile
from simulator.stats import Stats


@dataclass
class SimConfig:
    url: str
    admin_phone: str
    riders: int = 8
    passengers: int = 16
    minutes: float = 10.0
    seed: int = 1
    profile: Profile = field(default_factory=Profile)
    max_rides: int | None = None            # para depois de tantos pedidos (e de as corridas terminarem)
    drain_s: float = 900.0                  # o máximo a esperar, no fim, para as corridas abertas terminarem
    state_dir: Path | None = None           # onde guardar os tokens entre rodadas
    status_every_s: float = 10.0
    on_status: Callable[[str], None] | None = None


@dataclass
class Outcome:
    config: SimConfig
    stats: Stats
    audit: dict
    seconds: float
    riders_online_peak: int = 0
