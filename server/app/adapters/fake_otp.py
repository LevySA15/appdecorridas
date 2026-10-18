"""Envio de código falso, para testes e para o simulador. Guarda o que "enviou"."""
from __future__ import annotations


class FakeOtpSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))

    def last_code(self, phone: str) -> str:
        return next(code for p, code in reversed(self.sent) if p == phone)
