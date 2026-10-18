"""Aviso ao contato de emergência falso, para testes e para o servidor de desenvolvimento."""
from __future__ import annotations

import logging

log = logging.getLogger("app.notifier")


class FakeContactNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False           # os testes ligam para simular o WhatsApp fora do ar

    def notify(self, phone: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("canal de aviso fora do ar")
        self.sent.append((phone, text))
        del self.sent[:-200]
        log.info("aviso para %s: %s", phone, text)
