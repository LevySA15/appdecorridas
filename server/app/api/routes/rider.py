"""Rotas do motoqueiro: cadastro, disponibilidade, posição, ofertas e andamento da corrida."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.body import read_limited
from app.api.deps import get_runtime, rider_user
from app.api.views import rider_ride_view, rider_state
from app.db import queries
from app.domain.clock import local_date
from app.domain.geo import GeoPoint
from app.domain.rides import WrongPin
from app.infra.documents import KINDS, MAX_UPLOAD_BYTES, DocumentStore, UploadError
from app.services.auth import AuthUser, TooManyRequests
from app.services.riders import RegistrationError

router = APIRouter(prefix="/v1/rider", tags=["motoqueiro"])

DocKind = Literal["selfie", "cnh", "crlv"]
UPLOADS_PER_HOUR = 30
PIN_ATTEMPTS = 5            # códigos errados por corrida...
PIN_WINDOW_S = 600          # ...nesta janela, depois trava (4 dígitos não podem ser adivinhados no tapa)
_ON_THE_MOVE = ("accepted", "arrived", "in_progress")
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


class PositionIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class StartIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")


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
    data = await read_limited(
        request, MAX_UPLOAD_BYTES, lambda: UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
    )
    return await run_in_threadpool(_save_upload, get_runtime(request), user.user_id, kind, data)


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


@router.get("/state")
def state(request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    return get_runtime(request).run(lambda unit: rider_state(unit, user.user_id))


@router.post("/online", status_code=204)
def go_online(request: Request, user: AuthUser = Depends(rider_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.go_online(unit.session, user.user_id, local_date(unit.now)))
    return Response(status_code=204)


@router.post("/offline", status_code=204)
def go_offline(request: Request, user: AuthUser = Depends(rider_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.go_offline(unit.session, user.user_id))
    return Response(status_code=204)


@router.post("/position", status_code=204)
def report_position(body: PositionIn, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
    """A cada ~4 s enquanto disponível. Quem está parado não entra no mapa; na corrida, o passageiro acompanha."""

    def work(unit):
        context = queries.rider_context(unit.session, user.user_id)
        if context is None or not context.online:
            return
        point = GeoPoint(body.lat, body.lng)
        unit.riders.report_position(user.user_id, point, unit.now)
        if context.ride_id is not None and context.ride_state in _ON_THE_MOVE:
            unit.events.add(
                context.passenger_id, "rider_position", {"ride_id": context.ride_id, "lat": body.lat, "lng": body.lng}
            )
            if context.ride_state == "in_progress":
                unit.safety.on_rider_position(unit.session, context.ride_id, context.passenger_id, point, unit.now)

    get_runtime(request).run(work)
    return Response(status_code=204)


@router.post("/entry-charge", status_code=201)
def entry_charge(request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    def work(unit):
        charge = unit.payments.start_entry_charge(unit.session, user.user_id)
        return {"charge_id": charge.charge_id, "amount_cents": charge.amount_cents, "br_code": charge.br_code}

    return get_runtime(request).run(work)


@router.post("/offers/{ride_id}/accept")
def accept_offer(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    def work(unit):
        unit.dispatch.accept_offer(unit.session, user.user_id, ride_id, unit.now)
        return rider_ride_view(unit, ride_id)

    return get_runtime(request).run(work)


@router.post("/offers/{ride_id}/decline", status_code=204)
def decline_offer(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.dispatch.decline_offer(unit.session, user.user_id, ride_id, unit.now))
    return Response(status_code=204)


def _step(request: Request, user: AuthUser, ride_id: str, action) -> dict:
    def work(unit):
        action(unit)
        return rider_ride_view(unit, ride_id)

    return get_runtime(request).run(work)


@router.post("/rides/{ride_id}/arrive")
def arrive(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    return _step(request, user, ride_id, lambda u: u.trips.arrive(u.session, user.user_id, ride_id, u.now))


@router.post("/rides/{ride_id}/helmet")
def confirm_helmet(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    return _step(request, user, ride_id, lambda u: u.trips.confirm_helmet(u.session, user.user_id, ride_id, u.now))


@router.post("/rides/{ride_id}/start")
def start_trip(ride_id: str, body: StartIn, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    runtime = get_runtime(request)
    key = f"pin:{ride_id}"

    def action(unit):
        if runtime.limiter.count(key, PIN_WINDOW_S, unit.now) >= PIN_ATTEMPTS:
            raise TooManyRequests("Muitas tentativas de código. Espere alguns minutos e confira com o passageiro.")
        try:
            unit.trips.start_trip(unit.session, user.user_id, ride_id, body.pin, unit.now)
        except WrongPin:
            runtime.limiter.hit(key, PIN_ATTEMPTS, PIN_WINDOW_S, unit.now)
            raise

    return _step(request, user, ride_id, action)


@router.post("/rides/{ride_id}/complete")
def complete_trip(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    return _step(request, user, ride_id, lambda u: u.trips.complete_trip(u.session, user.user_id, ride_id, u.now))


@router.post("/rides/{ride_id}/cash-received", status_code=204)
def cash_received(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
    get_runtime(request).run(
        lambda unit: unit.trips.confirm_cash_received(unit.session, user.user_id, ride_id, unit.now)
    )
    return Response(status_code=204)


assert set(DocKind.__args__) == set(KINDS)      # a lista da rota e a do armazenamento não podem divergir
