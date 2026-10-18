"""Rotas do passageiro: preço, pedido, cancelamento, contato de emergência e estado."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, passenger_user
from app.api.schemas import PlaceIn
from app.api.views import passenger_ride_view, passenger_state, quote_view
from app.db import repositories as repo
from app.domain.types import PaymentMethod
from app.services.auth import AuthUser, normalize_phone
from app.services.quotes import NotAllowed

router = APIRouter(prefix="/v1/passenger", tags=["passageiro"])


class QuoteIn(BaseModel):
    pickup: PlaceIn
    destination: PlaceIn


class RideIn(BaseModel):
    quote_id: str = Field(min_length=1, max_length=40)
    method: Literal["pix", "cash"]


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)


@router.post("/quotes")
def create_quote(body: QuoteIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)

    def work(unit):
        quote = unit.quotes.create_quote(
            unit.session, user.user_id, body.pickup.point, body.destination.point,
            body.pickup.text, body.destination.text, unit.now,
        )
        return quote_view(quote, runtime.payment_methods(unit.now))

    return runtime.run(work)


@router.post("/rides", status_code=201)
def request_ride(body: RideIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)

    def work(unit):
        method = PaymentMethod(body.method)
        if method is PaymentMethod.PIX and runtime.pix_health.is_down(unit.now):
            raise NotAllowed("O Pix está fora do ar agora. Escolha pagar em dinheiro.")
        ride = unit.requests.request_ride(unit.session, user.user_id, body.quote_id, method, unit.now)
        return passenger_ride_view(unit, ride.ride_id)

    return runtime.run(work)


@router.post("/rides/{ride_id}/cancel")
def cancel_ride(ride_id: str, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    result = get_runtime(request).run(
        lambda unit: unit.trips.cancel_by_passenger(unit.session, user.user_id, ride_id, unit.now)
    )
    # A compensação do cancelamento tardio ainda não é cobrada (política em aberto): não é prometida ao app.
    return {"refund": result.refund_needed}


@router.get("/state")
def state(request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)
    return runtime.run(lambda unit: passenger_state(unit, user.user_id, runtime.payment_methods(unit.now)))


@router.put("/emergency-contact", status_code=204)
def set_emergency_contact(body: ContactIn, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    phone = normalize_phone(body.phone)
    if phone == user.phone:
        raise ValueError("Use o número de outra pessoa, que possa te ajudar.")
    get_runtime(request).run(
        lambda unit: repo.set_emergency_contact(unit.session, user.user_id, body.name.strip(), phone)
    )
    return Response(status_code=204)
