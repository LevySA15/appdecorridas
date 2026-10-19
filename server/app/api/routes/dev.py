"""Ajudas só do modo de desenvolvimento (o simulador e os testes à mão usam). Em produção nem existem."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_runtime
from app.api.errors import ApiError
from app.api.webhook import process_pix_event
from app.db import queries
from app.db.pg_ledger import PgLedger
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


@router.get("/audit")
def audit(request: Request) -> dict:
    """Conferência de fim de dia para o simulador: o livro-caixa fecha, bate com o provedor e não sobrou corrida aberta?"""
    runtime = get_runtime(request)

    def work(unit):
        ledger = PgLedger(unit.session)
        extract = {
            (f"entry:{c.rider_id}" if c.purpose == "entry" else f"charge:{c.charge_id}"): c.amount_cents - c.refunded_cents
            for c in runtime.provider.charges.values()
            if c.paid and c.amount_cents - c.refunded_cents > 0     # devolução parcial deixa o resto com o provedor
        }
        return {
            "ledger_balanced": ledger.is_balanced(),
            "reconcile_diff": ledger.reconcile(extract),
            "rides_by_state": queries.count_rides_by_state(unit.session),
            "open_rides": queries.open_rides(unit.session),
            "double_booked_riders": queries.riders_with_two_active_rides(unit.session),
            "balance_matches_ledger": queries.passenger_balances_total(unit.session)
            == queries.ledger_balances_total(unit.session),
            "inconsistent_fees": queries.inconsistent_fee_ids(unit.session),
        }

    return runtime.run(work)
