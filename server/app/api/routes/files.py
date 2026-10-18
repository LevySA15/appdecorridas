"""Ver a foto de um documento do motoqueiro. Nunca é um endereço público: sempre exige login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_user, get_runtime
from app.api.errors import ApiError
from app.api.routes.rider import DocKind
from app.db import queries
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1", tags=["documentos"])


@router.get("/riders/{rider_id}/documents/{kind}")
def get_document(rider_id: str, kind: DocKind, request: Request, user: AuthUser = Depends(current_user)) -> Response:
    """O administrador e o próprio motoqueiro veem tudo. O passageiro vê só a selfie, de quem já o buscou."""
    runtime = get_runtime(request)

    def work(unit):
        allowed = user.role == "admin" or user.user_id == rider_id or (
            user.role == "passenger" and kind == "selfie"
            and queries.passenger_rode_with(unit.session, user.user_id, rider_id)
        )
        if not allowed:
            raise ApiError(403, "forbidden", "Você não pode ver este documento.")
        key = queries.rider_document_key(unit.session, rider_id, kind)
        if key is None:
            raise LookupError(f"documento {kind} de {rider_id} não encontrado")
        return key

    data, media_type = runtime.documents.read(runtime.run(work))
    return Response(
        data, media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
