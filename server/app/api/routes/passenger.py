"""Rotas do passageiro: preço, pedido, cancelamento, contato de emergência e estado."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, passenger_user
from app.api.schemas import PlaceIn
from app.api.views import passenger_history, passenger_ride_view, passenger_state, quote_view
from app.db import repositories as repo
from app.domain.geo import GeoPoint
from app.domain.types import PaymentMethod
from app.services.auth import AuthUser, TooManyRequests, normalize_phone
from app.services.quotes import NotAllowed

router = APIRouter(prefix="/v1/passenger", tags=["passageiro"])

# Quem cota ou pede corrida sem parar gasta o mapa pago (Google) e a fila dos motoqueiros: um passageiro de verdade
# não chega nem perto destes números (cotar de novo a cada ajuste do ponto é o uso mais intenso).
QUOTES_PER_MINUTE = 20
RIDE_REQUESTS_PER_MINUTE = 8
# O endereço escrito é pedido duas vezes por cotação (embarque e destino): o dobro das cotações.
ADDRESS_LOOKUPS_PER_MINUTE = 40


def _slow_down(runtime, what: str, passenger_id: str, limit: int) -> None:
    if not runtime.limiter.hit(f"{what}:{passenger_id}", limit, 60, runtime.clock()):
        raise TooManyRequests("Calma! Muitas tentativas seguidas. Espere um minuto e tente de novo.")


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


class WithdrawIn(BaseModel):
    amount_cents: int
    pix_key: str = Field(min_length=1, max_length=100)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)


@router.post("/quotes")
def create_quote(body: QuoteIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)
    _slow_down(runtime, "quote", user.user_id, QUOTES_PER_MINUTE)

    def work(unit):
        quote = unit.quotes.create_quote(
            unit.session, user.user_id, body.pickup.point, body.destination.point,
            body.pickup.text, body.destination.text, unit.now,
        )
        methods = runtime.payment_methods(unit.now)
        saldo = repo.get_passenger_account(unit.session, user.user_id).balance_cents
        if unit.cfg.balance.pay_rides_enabled and saldo >= quote.price_cents:
            methods = [*methods, "balance"]            # o saldo cobre a corrida inteira
        return quote_view(quote, methods)

    return runtime.run(work)


@router.get("/address")
def point_address(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    user: AuthUser = Depends(passenger_user),
) -> dict:
    """O endereço escrito de um ponto do mapa (`{"text": "Rua X, 12 - Bairro"}`, ou `text` nulo se não souber).

    O servidor é quem fala com o Google (a chave não vai para o celular) e quem guarda o teto de gasto; sem a chave do
    Google responde sempre `text` nulo e o app segue sem endereço."""
    runtime = get_runtime(request)
    _slow_down(runtime, "address", user.user_id, ADDRESS_LOOKUPS_PER_MINUTE)
    return {"text": runtime.maps.describe(GeoPoint(lat, lng))}


@router.post("/rides", status_code=201)
def request_ride(body: RideIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)
    _slow_down(runtime, "ride-request", user.user_id, RIDE_REQUESTS_PER_MINUTE)

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


@router.post("/balance/withdraw", status_code=201)
def withdraw_balance(body: WithdrawIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    """Saca parte do saldo por Pix. Desligado por padrão (erro `withdraw_disabled`)."""

    def work(unit):
        saque = unit.money.withdraw(unit.session, user.user_id, body.amount_cents, body.pix_key, unit.now)
        saldo = repo.get_passenger_account(unit.session, user.user_id).balance_cents
        return {
            "withdrawal_id": saque.withdrawal_id, "amount_cents": saque.amount_cents, "balance_cents": saldo,
            "key": saque.key_masked,
        }

    return get_runtime(request).run(work)


@router.get("/state")
def state(request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)
    return runtime.run(lambda unit: passenger_state(unit, user.user_id, runtime.payment_methods(unit.now)))


@router.get("/rides")
def ride_history(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(passenger_user),
) -> dict:
    """O histórico: só as corridas encerradas (a que está aberta vem no `/state`), da mais nova para a mais antiga."""
    return get_runtime(request).run(lambda unit: passenger_history(unit, user.user_id, limit, offset))


@router.put("/emergency-contact", status_code=204)
def set_emergency_contact(body: ContactIn, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    phone = normalize_phone(body.phone)
    if phone == user.phone:
        raise ValueError("Use o número de outra pessoa, que possa te ajudar.")
    get_runtime(request).run(
        lambda unit: repo.set_emergency_contact(unit.session, user.user_id, body.name.strip(), phone)
    )
    return Response(status_code=204)
