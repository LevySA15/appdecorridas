"""Aviso de pagamento do provedor (Pix). Aqui só existe o formato interno e a assinatura HMAC.

O adaptador real da Woovi (plano 7) traduz o aviso dela para este formato e troca a verificação de
assinatura; o resto (conferir valor e corrida, tratar cada aviso uma vez só) já fica pronto.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

from app.api.errors import ApiError
from app.db import repositories as repo

if TYPE_CHECKING:       # só para os tipos: `app.runtime` importa este módulo
    from app.runtime import Runtime

log = logging.getLogger("app.webhook")

SIGNATURE_HEADER = "x-signature"
MAX_WEBHOOK_BYTES = 16 * 1024


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookVerifier(Protocol):
    def verify(self, headers: Mapping[str, str], body: bytes) -> bool: ...


class HmacVerifier:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("o segredo do aviso do provedor não pode ser vazio")
        self.secret = secret

    def verify(self, headers: Mapping[str, str], body: bytes) -> bool:
        received = headers.get(SIGNATURE_HEADER, "")
        return hmac.compare_digest(received.encode(), sign(self.secret, body).encode())


class PixEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    type: Literal["paid"]
    charge_id: str = Field(min_length=1, max_length=40)
    ride_id: str | None = Field(default=None, max_length=40)
    amount_cents: int = Field(gt=0)


def process_pix_event(runtime: "Runtime", event: dict) -> str:
    """Confere o aviso com a cobrança guardada e o aplica. Devolve "applied", "refunded", "duplicate" ou
    "unknown_charge". Valor ou corrida diferentes da cobrança viram erro 409 e **não gastam** o id do aviso."""

    def work(unit):
        try:
            charge = repo.get_charge(unit.session, event["charge_id"])
        except LookupError:
            log.warning("aviso %s de cobrança desconhecida %s", event["event_id"], event["charge_id"])
            return "unknown_charge"
        if charge.amount_cents != event["amount_cents"] or (charge.ride_id or "") != (event.get("ride_id") or ""):
            log.error("aviso %s não bate com a cobrança %s (valor ou corrida)", event["event_id"], charge.charge_id)
            raise ApiError(409, "event_mismatch", "O aviso não confere com a cobrança.")
        return unit.payments.on_provider_event(unit.session, event)

    return runtime.run(work)
