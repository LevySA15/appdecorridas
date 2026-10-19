"""Rotas do administrador (o painel completo é o plano 4; aqui só o que o fluxo precisa para andar)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import admin_user, get_runtime
from app.db import queries
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/admin", tags=["administrador"])


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=200)


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    note: str = Field(default="", max_length=200)


def _rider_item(item: queries.RiderListItem) -> dict:
    return {
        "rider_id": item.rider_id, "name": item.name, "phone": item.phone, "cpf": item.cpf, "plate": item.plate,
        "moto_model": item.moto_model, "status": item.status, "reason": item.reason,
        "cnh_expires_on": item.cnh_expires_on.isoformat() if item.cnh_expires_on else None,
        "crlv_expires_on": item.crlv_expires_on.isoformat() if item.crlv_expires_on else None,
        "documents": list(item.documents),
    }


@router.get("/riders")
def list_riders(
    request: Request,
    status: Literal["pending", "approved", "blocked", "rejected"] = "pending",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    items = get_runtime(request).run(lambda unit: queries.list_riders(unit.session, status, limit, offset))
    return [_rider_item(item) for item in items]


@router.post("/riders/{rider_id}/approve", status_code=204)
def approve(rider_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.approve(unit.session, rider_id, unit.now))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/reject", status_code=204)
def reject(rider_id: str, body: ReasonIn, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.reject(unit.session, rider_id, body.reason))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/block", status_code=204)
def block(rider_id: str, body: ReasonIn, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.block(unit.session, rider_id, body.reason))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/unblock", status_code=204)
def unblock(rider_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.unblock(unit.session, rider_id))
    return Response(status_code=204)


@router.get("/safety-alerts")
def list_safety_alerts(
    request: Request,
    status: Literal["open", "ok", "sos", "resolved"] = "open",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    items = get_runtime(request).run(lambda unit: queries.list_safety_alerts(unit.session, status, limit, offset))
    return [
        {
            "alert_id": i.alert_id, "ride_id": i.ride_id, "kind": i.kind, "status": i.status,
            "suspected_mock": i.suspected_mock, "lat": i.lat, "lng": i.lng, "created_at": i.created_at,
            "answered_at": i.answered_at, "resolved_at": i.resolved_at, "note": i.note,
            "passenger_name": i.passenger_name, "rider_name": i.rider_name, "plate": i.plate,
        }
        for i in items
    ]


@router.post("/safety-alerts/{alert_id}/resolve", status_code=204)
def resolve_safety_alert(
    alert_id: int, body: NoteIn, request: Request, admin: AuthUser = Depends(admin_user)
) -> Response:
    get_runtime(request).run(
        lambda unit: unit.safety.resolve(unit.session, alert_id, admin.user_id, body.note, unit.now)
    )
    return Response(status_code=204)


@router.get("/appeals")
def list_appeals(
    request: Request,
    status: Literal["open", "accepted", "rejected"] = "open",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    """Recursos da taxa de cancelamento tardio, o mais antigo primeiro."""
    items = get_runtime(request).run(lambda unit: queries.list_appeals(unit.session, status, limit, offset))
    return [
        {
            "ride_id": i.ride_id, "passenger_id": i.passenger_id, "passenger_name": i.passenger_name,
            "rider_name": i.rider_name, "fee_cents": i.fee_cents, "reason": i.reason, "created_at": i.created_at,
            "appeal_state": i.appeal_state, "appeal_text": i.appeal_text, "appealed_at": i.appealed_at,
            "decided_at": i.decided_at, "decision_note": i.decision_note,
        }
        for i in items
    ]


@router.post("/appeals/{ride_id}/decide", status_code=204)
def decide_appeal(ride_id: str, body: DecisionIn, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(
        lambda unit: unit.money.decide_appeal(
            unit.session, admin.user_id, ride_id, body.decision == "accept", body.note, unit.now
        )
    )
    return Response(status_code=204)


# --- leituras do painel -------------------------------------------------------------------------------------

RideState = Literal["requested", "searching", "queued", "accepted", "arrived", "in_progress", "completed", "cancelled", "no_rider"]


@router.get("/rides")
def list_rides(
    request: Request,
    state: RideState | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    items = get_runtime(request).run(lambda unit: queries.list_rides(unit.session, state, limit, offset))
    return [i.__dict__ for i in items]


@router.get("/rides/{ride_id}")
def ride_detail(ride_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> dict:
    found = get_runtime(request).run(lambda unit: queries.ride_detail(unit.session, ride_id))
    if found is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    return found


@router.get("/passengers")
def list_passengers(
    request: Request,
    q: str | None = Query(None, max_length=60),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    return get_runtime(request).run(lambda unit: queries.list_passengers(unit.session, q, limit, offset))


@router.get("/debtors")
def debtors(request: Request, admin: AuthUser = Depends(admin_user)) -> dict:
    return get_runtime(request).run(lambda unit: queries.list_debtors(unit.session))


@router.get("/money")
def money(request: Request, admin: AuthUser = Depends(admin_user)) -> dict:
    return get_runtime(request).run(lambda unit: queries.money_summary(unit.session))
