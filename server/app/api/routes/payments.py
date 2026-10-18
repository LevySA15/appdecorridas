"""Aviso do provedor de pagamento e consulta da cobrança (para o app desenhar o QR do Pix)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.api.body import read_limited
from app.api.deps import current_user, get_runtime
from app.api.errors import ApiError
from app.api.webhook import MAX_WEBHOOK_BYTES, PixEvent, process_pix_event
from app.db import repositories as repo
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1", tags=["pagamentos"])


@router.post("/webhooks/pix")
async def pix_webhook(request: Request) -> dict:
    runtime = get_runtime(request)
    body = await read_limited(
        request, MAX_WEBHOOK_BYTES, lambda: ApiError(413, "too_large", "Aviso grande demais.")
    )
    if not runtime.webhook_verifier.verify(request.headers, body):
        raise ApiError(401, "bad_signature", "Assinatura inválida.")
    try:
        event = PixEvent.model_validate_json(body)
    except ValidationError:
        raise ApiError(422, "invalid", "Aviso ilegível.") from None
    return {"status": await run_in_threadpool(process_pix_event, runtime, event.model_dump())}


@router.get("/charges/{charge_id}")
def get_charge(charge_id: str, request: Request, user: AuthUser = Depends(current_user)) -> dict:
    """Quem pode ver: o motoqueiro da cobrança, o passageiro da corrida e o administrador."""

    def work(unit):
        charge = repo.get_charge(unit.session, charge_id)
        allowed = user.role == "admin" or user.user_id == charge.rider_id
        if not allowed and charge.purpose != "entry" and charge.ride_id:
            allowed = repo.get_ride(unit.session, charge.ride_id).passenger_id == user.user_id
        if not allowed:
            raise ApiError(403, "forbidden", "Você não pode ver esta cobrança.")
        return {
            "charge_id": charge.charge_id, "purpose": charge.purpose, "ride_id": charge.ride_id or None,
            "amount_cents": charge.amount_cents, "paid": charge.paid, "br_code": charge.br_code,
        }

    return get_runtime(request).run(work)
