"""Rotas que os dois lados usam na mesma corrida."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_runtime, require_role
from app.api.schemas import StarsIn
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/rides", tags=["corrida"])


@router.post("/{ride_id}/rating", status_code=204)
def rate(
    ride_id: str, body: StarsIn, request: Request, user: AuthUser = Depends(require_role("passenger", "rider"))
) -> Response:
    get_runtime(request).run(lambda unit: unit.trips.rate(unit.session, user.user_id, ride_id, body.stars, unit.now))
    return Response(status_code=204)
