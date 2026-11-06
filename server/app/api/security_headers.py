"""Cabeçalhos de segurança das respostas HTTP.

Toda resposta ganha os básicos; o site do painel (`/painel`) ganha também a política de conteúdo, que só deixa
a página usar arquivos do próprio servidor. HSTS fica no proxy (Caddy): só faz sentido com HTTPS.
"""
from __future__ import annotations

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BASICOS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}

# O painel não tem script nem estilo dentro da página e só fala com o próprio endereço (vigiado por
# `tests/api/test_security_headers.py::test_painel_cabe_na_politica`). `blob:` é a foto de documento aberta numa aba nova.
PAINEL_CSP = (
    "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class _SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        caminho = scope["path"]
        painel = caminho == "/painel" or caminho.startswith("/painel/")

        async def send_com_cabecalhos(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabecalhos = MutableHeaders(scope=message)
                for nome, valor in BASICOS.items():
                    cabecalhos.setdefault(nome, valor)
                if painel:
                    cabecalhos.setdefault("content-security-policy", PAINEL_CSP)
            await send(message)

        await self.app(scope, receive, send_com_cabecalhos)


def install_security_headers(app: FastAPI) -> None:
    app.add_middleware(_SecurityHeaders)
