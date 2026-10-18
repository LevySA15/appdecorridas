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
