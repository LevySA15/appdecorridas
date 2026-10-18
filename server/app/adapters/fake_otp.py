"""Envio de código falso, para testes e para o simulador. Guarda o que "enviou"."""
from __future__ import annotations

import logging

log = logging.getLogger("app.otp")


class FakeOtpSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))

    def last_code(self, phone: str) -> str:
        return next(code for p, code in reversed(self.sent) if p == phone)


class DevOtpSender(FakeOtpSender):
    """Servidor de desenvolvimento: ainda não há WhatsApp (plano 7), então o código vai para o registro."""

    def send(self, phone: str, code: str) -> None:
        super().send(phone, code)
        del self.sent[:-200]
        log.info("código de login de %s: %s", phone, code)
