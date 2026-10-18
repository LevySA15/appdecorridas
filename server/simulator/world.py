"""O que todos os atores dividem: a API, as anotações, o perfil, o relógio e o que é dito em voz alta (o código da corrida)."""
from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from simulator.api import Api
from simulator.behavior import Choices, Profile
from simulator.stats import Stats


class SimulationError(Exception):
    """A simulação não consegue seguir (por exemplo, não conseguiu entrar no servidor)."""


@dataclass(frozen=True)
class Login:
    user_id: str
    token: str
    phone: str
    role: str


class TokenCache:
    """Guarda os tokens entre uma rodada e outra, para não pedir código de novo (o servidor limita pedidos por hora)."""

    def __init__(self, path: Path | None, url: str) -> None:
        self.path = path
        self.url = url
        self._data: dict[str, dict[str, dict]] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}

    def get(self, phone: str) -> dict | None:
        return self._data.get(self.url, {}).get(phone)

    def put(self, phone: str, token: str, user_id: str) -> None:
        self._data.setdefault(self.url, {})[phone] = {"token": token, "user_id": user_id}

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".part")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle)
        os.replace(temp, self.path)


@dataclass
class World:
    api: Api
    stats: Stats
    profile: Profile
    ws_url: str
    seed: int
    clock: Callable[[], float] = time.monotonic
    requests_left: int | None = None            # None = sem limite de pedidos
    accepting: bool = True                      # passageiros ainda pedem corridas novas
    stopped: bool = False                       # acabou: todos os atores saem
    pins: dict[str, str] = field(default_factory=dict)     # corrida -> código que o passageiro disse ao motoqueiro

    def now(self) -> float:
        return self.clock()

    def choices(self, kind: str, index: int) -> Choices:
        return Choices(random.Random(f"{self.seed}-{kind}-{index}"), self.profile)

    def reserve_request(self) -> bool:
        """Pede uma vaga no limite total de pedidos da rodada (`--max-rides`)."""
        if not self.accepting:
            return False
        if self.requests_left is None:
            return True
        if self.requests_left <= 0:
            return False
        self.requests_left -= 1
        return True

    def release_request(self) -> None:
        if self.requests_left is not None:
            self.requests_left += 1

    async def pay_pix(self, charge_id: str) -> None:
        """Faz de conta que o passageiro pagou o Pix (só existe no modo de desenvolvimento do servidor)."""
        await self.api.call("POST", "/v1/dev/pix/{charge_id}/pay", params={"charge_id": charge_id}, ok=("not_found",))


async def login(api: Api, cache: TokenCache, phone: str, role: str) -> Login:
    """Entra com um número: reaproveita o token guardado se ainda vale; senão pede o código (que no modo de desenvolvimento
    o servidor entrega em /v1/dev/otp) e entra."""
    cached = cache.get(phone)
    if cached is not None:
        me = await api.call("GET", "/v1/me", token=cached["token"], ok=("unauthorized",))
        if me.ok and me.body.get("role") == role:
            return Login(cached["user_id"], cached["token"], phone, role)
    sent = await api.call("POST", "/v1/auth/code", json={"phone": phone}, ok=("too_many_requests",))
    if not sent.ok:
        raise SimulationError(f"não consegui pedir o código para {phone}: {sent.message or sent.status}")
    otp = await api.call("GET", "/v1/dev/otp", query={"phone": phone})
    if not otp.ok:
        raise SimulationError("o servidor não está em modo de desenvolvimento (falta /v1/dev/otp)")
    verified = await api.call(
        "POST", "/v1/auth/verify",
        json={"phone": phone, "code": otp.body["code"], "role": role, "device": "simulador"},
        ok=("code_invalid",),
    )
    if not verified.ok:
        raise SimulationError(f"não consegui entrar com {phone} como {role}: {verified.message}")
    cache.put(phone, verified.body["token"], verified.body["user_id"])
    return Login(verified.body["user_id"], verified.body["token"], phone, role)
