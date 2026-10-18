"""SOS e resposta ao aviso de segurança, do lado do passageiro."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_runtime, passenger_user
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/rides", tags=["segurança"])


@router.post("/{ride_id}/sos")
def sos(ride_id: str, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    """Vale durante toda a corrida, não só depois de um aviso. O app liga para o 190; aqui avisamos o resto."""
    result = get_runtime(request).run(lambda unit: unit.safety.sos(unit.session, user.user_id, ride_id, unit.now))
    return {
        "alert_id": result.alert_id, "contact_registered": result.contact_registered,
        "contact_notified": result.contact_notified, "repeated": result.repeated, "emergency_number": "190",
    }


@router.post("/{ride_id}/safety/{alert_id}/ok", status_code=204)
def safety_ok(ride_id: str, alert_id: int, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    get_runtime(request).run(
        lambda unit: unit.safety.answer_ok(unit.session, user.user_id, ride_id, alert_id, unit.now)
    )
    return Response(status_code=204)
