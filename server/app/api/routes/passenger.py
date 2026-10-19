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
    method: Literal["pix", "cash", "balance"]


class AppealIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class TopupIn(BaseModel):
    amount_cents: int


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
        with_balance = body.method == "balance"        # corrida Pix quitada com o saldo no aceite da moto
        method = PaymentMethod.PIX if with_balance else PaymentMethod(body.method)
        if method is PaymentMethod.PIX and not with_balance and runtime.pix_health.is_down(unit.now):
            raise NotAllowed("O Pix está fora do ar agora. Escolha pagar em dinheiro.")
        ride = unit.requests.request_ride(
            unit.session, user.user_id, body.quote_id, method, unit.now, pay_with_balance=with_balance
        )
        return passenger_ride_view(unit, ride.ride_id)

    return runtime.run(work)


@router.post("/rides/{ride_id}/cancel")
def cancel_ride(ride_id: str, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    def work(unit):
        outcome = unit.trips.cancel_by_passenger(unit.session, user.user_id, ride_id, unit.now)
        return {
            "refund": outcome.refund_needed, "fee_cents": outcome.fee_cents,
            "fee": None if outcome.fee_cents == 0 else {
                "from_balance_cents": outcome.from_balance_cents, "retained_cents": outcome.retained_cents,
                "pending_cents": outcome.pending_cents,
            },
            "refund_to": outcome.refund_to,
            "balance_cents": repo.get_passenger_account(unit.session, user.user_id).balance_cents,
        }

    return get_runtime(request).run(work)


@router.post("/fees/pay")
def pay_pending_fee(request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    """Paga a taxa de cancelamento pendente: com o saldo, se ele cobre tudo; senão devolve a cobrança Pix."""

    def work(unit):
        charge = unit.money.pay_pending(unit.session, user.user_id, unit.now)
        if charge is None:
            return {"paid": True}
        return {"paid": False, "charge_id": charge.charge_id, "amount_cents": charge.amount_cents, "br_code": charge.br_code}

    return get_runtime(request).run(work)


@router.post("/rides/{ride_id}/fee/appeal", status_code=204)
def appeal_fee(ride_id: str, body: AppealIn, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.money.file_appeal(unit.session, user.user_id, ride_id, body.text, unit.now))
    return Response(status_code=204)


@router.post("/balance/topup")
def topup_balance(body: TopupIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    """Cobrança Pix para recarregar o saldo. Desligada por padrão (erro `topup_disabled`)."""

    def work(unit):
        charge = unit.money.topup(unit.session, user.user_id, body.amount_cents, unit.now)
        return {"charge_id": charge.charge_id, "amount_cents": charge.amount_cents, "br_code": charge.br_code}

    return get_runtime(request).run(work)


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
