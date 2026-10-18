"""Rotas do motoqueiro: documentos e cadastro. (Disponibilidade e corridas entram na próxima tarefa.)"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, rider_user
from app.domain.clock import local_date
from app.infra.documents import KINDS, MAX_UPLOAD_BYTES, DocumentStore, UploadError
from app.services.auth import AuthUser, TooManyRequests
from app.services.riders import RegistrationError

router = APIRouter(prefix="/v1/rider", tags=["motoqueiro"])

DocKind = Literal["selfie", "cnh", "crlv"]
UPLOADS_PER_HOUR = 30
_KIND_NAMES = {"selfie": "o seu rosto (selfie)", "cnh": "a CNH", "crlv": "o documento da moto"}


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    cpf: str = Field(max_length=20)
    cnh_number: str = Field(max_length=20)
    plate: str = Field(max_length=10)
    moto_model: str = Field(min_length=1, max_length=80)
    selfie_key: str = Field(max_length=200)
    cnh_photo_key: str = Field(max_length=200)
    crlv_key: str = Field(max_length=200)
    cnh_expires_on: dt.date
    crlv_expires_on: dt.date


class RenewIn(BaseModel):
    cnh_expires_on: dt.date
    crlv_expires_on: dt.date
    cnh_photo_key: str | None = Field(default=None, max_length=200)
    crlv_key: str | None = Field(default=None, max_length=200)


def check_own_document(documents: DocumentStore, rider_id: str, kind: str, key: str) -> str:
    """A foto precisa ter sido enviada por este motoqueiro, ser do tipo certo e existir."""
    owner, _, name = key.partition("/")
    if owner != rider_id or not name.startswith(f"{kind}-") or not documents.exists(key):
        raise RegistrationError(f"Envie de novo a foto d{_KIND_NAMES[kind]}.")
    return key


def _save_upload(runtime, rider_id: str, kind: str, data: bytes) -> dict:
    if not runtime.limiter.hit(f"upload:{rider_id}", UPLOADS_PER_HOUR, 3600, runtime.clock()):
        raise TooManyRequests("Muitas fotos enviadas. Tente de novo mais tarde.")
    return {"key": runtime.documents.save(rider_id, kind, data), "bytes": len(data)}


@router.put("/documents/{kind}", status_code=201)
async def upload_document(kind: DocKind, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    """Recebe a foto crua no corpo do pedido (sem formulário). Corta em 8 MB mesmo sem tamanho declarado."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
        chunks.append(chunk)
    return await run_in_threadpool(_save_upload, get_runtime(request), user.user_id, kind, b"".join(chunks))


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    runtime = get_runtime(request)
    keys = {
        "selfie": check_own_document(runtime.documents, user.user_id, "selfie", body.selfie_key),
        "cnh": check_own_document(runtime.documents, user.user_id, "cnh", body.cnh_photo_key),
        "crlv": check_own_document(runtime.documents, user.user_id, "crlv", body.crlv_key),
    }

    def work(unit):
        unit.riders.register_rider(
            unit.session, user.user_id, name=body.name, cpf=body.cpf, cnh_number=body.cnh_number, plate=body.plate,
            moto_model=body.moto_model, selfie_key=keys["selfie"], cnh_photo_key=keys["cnh"], crlv_key=keys["crlv"],
            cnh_expires_on=body.cnh_expires_on, crlv_expires_on=body.crlv_expires_on, today=local_date(unit.now),
        )

    runtime.run(work)
    return {"status": "pending"}


@router.post("/documents/renew", status_code=204)
def renew_documents(body: RenewIn, request: Request, user: AuthUser = Depends(rider_user)):
    runtime = get_runtime(request)
    cnh_key = check_own_document(runtime.documents, user.user_id, "cnh", body.cnh_photo_key) if body.cnh_photo_key else None
    crlv_key = check_own_document(runtime.documents, user.user_id, "crlv", body.crlv_key) if body.crlv_key else None
    runtime.run(
        lambda unit: unit.riders.renew_documents(
            unit.session, user.user_id, cnh_expires_on=body.cnh_expires_on, crlv_expires_on=body.crlv_expires_on,
            today=local_date(unit.now), cnh_photo_key=cnh_key, crlv_key=crlv_key,
        )
    )
    return Response(status_code=204)


assert set(DocKind.__args__) == set(KINDS)      # a lista da rota e a do armazenamento não podem divergir
