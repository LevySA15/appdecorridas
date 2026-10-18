"""Aviso a uma pessoa de fora do app (o contato de emergência do passageiro). O WhatsApp real é do plano 7."""
from __future__ import annotations

from typing import Protocol


class ContactNotifier(Protocol):
    def notify(self, phone: str, text: str) -> None: ...
