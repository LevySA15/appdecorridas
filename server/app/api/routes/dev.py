"""Ajudas só do modo de desenvolvimento (o simulador e os testes à mão usam). Em produção nem existem."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_runtime
from app.api.errors import ApiError
from app.api.webhook import process_pix_event
from app.services.auth import normalize_phone

router = APIRouter(prefix="/v1/dev", tags=["desenvolvimento"])


@router.get("/otp")
def last_otp(phone: str, request: Request) -> dict:
    """O último código de login enviado a um número (no lugar do WhatsApp, que só chega no plano 7)."""
    sender = get_runtime(request).otp_sender
    try:
        return {"code": sender.last_code(normalize_phone(phone))}
    except (StopIteration, AttributeError):
        raise ApiError(404, "not_found", "Nenhum código enviado para este número.") from None


@router.post("/pix/{charge_id}/pay")
def pay_pix(charge_id: str, request: Request) -> dict:
    """Faz de conta que o passageiro pagou o Pix: gera o aviso do provedor falso e o trata como o real."""
    runtime = get_runtime(request)
    try:
        event = runtime.provider.mark_paid(charge_id)
    except (KeyError, AttributeError):
        raise ApiError(404, "not_found", "Cobrança desconhecida.") from None
    return {"status": process_pix_event(runtime, event)}
