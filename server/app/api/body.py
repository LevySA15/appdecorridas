"""Leitura de corpo de pedido com teto de tamanho, mesmo quando o cliente não declara o tamanho."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Request


async def read_limited(request: Request, limit: int, too_big: Callable[[], Exception]) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_big()
        chunks.append(chunk)
    return b"".join(chunks)
