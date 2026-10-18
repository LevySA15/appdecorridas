"""Chamadas à API do servidor, todas anotadas: modelo da rota, resposta, tempo e se o erro era esperado."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx2 as httpx

from simulator.stats import Stats


@dataclass(frozen=True)
class Reply:
    status: int                      # 0 quando nem chegou resposta (servidor fora do ar, tempo esgotado)
    body: Any = None
    code: str | None = None          # o `code` estável do erro, quando é erro
    message: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Api:
    def __init__(
        self, base_url: str, stats: Stats, *, timeout: float = 20.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.stats = stats
        # o servidor fecha conexões ociosas em 5 s: reaproveitar uma já fechada daria erro de leitura
        limits = httpx.Limits(max_connections=300, max_keepalive_connections=100, keepalive_expiry=3.0)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, limits=limits, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        method: str,
        template: str,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        query: dict[str, Any] | None = None,
        ok: tuple[str, ...] = (),
    ) -> Reply:
        """`template` é a rota com `{marcadores}`; `params` os preenche. `ok` lista os erros que o chamador espera."""
        path = template.format(**(params or {}))
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        started = time.perf_counter()
        try:
            response = await self._client.request(
                method, path, headers=headers, json=json, content=content, params=query
            )
        except httpx.HTTPError as exc:
            self.stats.record_call(method, template, 0, time.perf_counter() - started)
            self.stats.flag(f"{method} {template}: sem resposta ({type(exc).__name__})")
            return Reply(0, message=str(exc))
        self.stats.record_call(method, template, response.status_code, time.perf_counter() - started)
        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = None
        code = message = None
        if response.status_code >= 400 and isinstance(body, dict) and isinstance(body.get("error"), dict):
            code, message = body["error"].get("code"), body["error"].get("message", "")
        reply = Reply(response.status_code, body, code, message or "")
        if response.status_code >= 500 or (response.status_code >= 400 and code not in ok):
            self.stats.flag(f"{method} {template}: {response.status_code} {code or ''} {message or ''}".strip())
        return reply
