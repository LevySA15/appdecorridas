"""Etapas da corrida, fila e cancelamento (spec, seção 5). Instantes em segundos (float)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.config import RideConfig
from app.domain.types import PaymentMethod

_DEFAULT = RideConfig()


class RideState(str, Enum):
    REQUESTED = "requested"
    SEARCHING = "searching"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_RIDER = "no_rider"


class InvalidTransition(Exception):
    """A ação não é permitida no estado atual da corrida."""


@dataclass
class Ride:
    ride_id: str
    passenger_id: str
    price_cents: int
    payment_method: PaymentMethod
    pin: str
    state: RideState = RideState.REQUESTED
    rider_id: str | None = None
    helmet_confirmed: bool = False
    pix_paid: bool = False
    pix_charge_created_at: float | None = None
    searching_since: float | None = None
    queued_since: float | None = None
    en_route_since: float | None = None
    arrived_at: float | None = None
    end_payment_confirmed: bool = False


def _require(ride: Ride, *states: RideState) -> None:
    if ride.state not in states:
        esperados = ", ".join(s.value for s in states)
        raise InvalidTransition(
            f"corrida {ride.ride_id}: estado {ride.state.value}, esperado {esperados}"
        )


def start_search(ride: Ride, now: float) -> None:
    _require(ride, RideState.REQUESTED)
    ride.state = RideState.SEARCHING
    ride.searching_since = now


def accept(ride: Ride, rider_id: str, now: float, rider_busy: bool) -> None:
    """O motoqueiro aceitou. Se ele ainda está em outra corrida, esta fica na fila."""
    _require(ride, RideState.SEARCHING)
    ride.rider_id = rider_id
    if ride.payment_method is PaymentMethod.PIX:
        ride.pix_charge_created_at = now
    if rider_busy:
        ride.state = RideState.QUEUED
        ride.queued_since = now
    else:
        ride.state = RideState.ACCEPTED
        ride.en_route_since = now


def promote_from_queue(ride: Ride, now: float) -> None:
    _require(ride, RideState.QUEUED)
    ride.state = RideState.ACCEPTED
    ride.en_route_since = now


def release_from_queue(ride: Ride, now: float) -> bool:
    """Tira a corrida da fila e volta para a busca. Devolve True se há Pix pago para estornar."""
    _require(ride, RideState.QUEUED)
    refund_needed = ride.pix_paid
    ride.state = RideState.SEARCHING
    ride.rider_id = None
    ride.pix_paid = False
    ride.pix_charge_created_at = None
    ride.queued_since = None
    ride.searching_since = now
    return refund_needed


def confirm_pix_paid(ride: Ride) -> None:
    _require(ride, RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED)
    if ride.payment_method is not PaymentMethod.PIX:
        raise InvalidTransition("esta corrida não é paga por Pix")
    ride.pix_paid = True


def pix_window_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.payment_method is not PaymentMethod.PIX or ride.pix_paid:
        return False
    if ride.state not in (RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED):
        return False
    if ride.pix_charge_created_at is None:
        return False
    return now - ride.pix_charge_created_at >= cfg.pix_window_s


def cancel_unpaid_pix(ride: Ride) -> None:
    """Cancela porque o passageiro não pagou o Pix a tempo. Sem compensação."""
    _require(ride, RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED)
    ride.state = RideState.CANCELLED


def mark_arrived(ride: Ride, now: float) -> None:
    _require(ride, RideState.ACCEPTED)
    ride.state = RideState.ARRIVED
    ride.arrived_at = now


def confirm_helmet(ride: Ride) -> None:
    _require(ride, RideState.ARRIVED)
    ride.helmet_confirmed = True


def start_ride(ride: Ride, pin: str) -> None:
    _require(ride, RideState.ARRIVED)
    if not ride.helmet_confirmed:
        raise InvalidTransition("o capacete extra ainda não foi confirmado")
    if ride.payment_method is PaymentMethod.PIX and not ride.pix_paid:
        raise InvalidTransition("o Pix ainda não foi pago")
    if pin != ride.pin:
        raise ValueError("código errado")
    ride.state = RideState.IN_PROGRESS


def complete(ride: Ride) -> None:
    _require(ride, RideState.IN_PROGRESS)
    ride.state = RideState.COMPLETED


def cancel(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> int:
    """Cancelamento pelo passageiro. Devolve a compensação ao motoqueiro, em centavos."""
    _require(
        ride,
        RideState.REQUESTED,
        RideState.SEARCHING,
        RideState.QUEUED,
        RideState.ACCEPTED,
        RideState.ARRIVED,
    )
    compensation = 0
    if ride.state in (RideState.ACCEPTED, RideState.ARRIVED):
        if ride.en_route_since is not None and now - ride.en_route_since > cfg.free_cancel_after_accept_s:
            compensation = cfg.cancel_compensation_cents
    ride.state = RideState.CANCELLED
    return compensation


def arrival_wait_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.state is not RideState.ARRIVED or ride.arrived_at is None:
        return False
    return now - ride.arrived_at >= cfg.max_wait_at_arrival_s


def cancel_after_arrival_timeout(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> int:
    if not arrival_wait_expired(ride, now, cfg):
        raise InvalidTransition("o tempo de espera na chegada ainda não acabou")
    ride.state = RideState.CANCELLED
    return cfg.cancel_compensation_cents


def mark_no_rider(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> None:
    _require(ride, RideState.SEARCHING)
    if ride.searching_since is None or now - ride.searching_since < cfg.search_give_up_s:
        raise InvalidTransition("ainda está dentro do tempo de procura")
    ride.state = RideState.NO_RIDER


def queue_wait_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.state is not RideState.QUEUED or ride.queued_since is None:
        return False
    return now - ride.queued_since >= cfg.queue_max_wait_s


def confirm_end_payment(ride: Ride) -> None:
    """O motoqueiro apertou "confirmar pagamento" ao fim de uma corrida paga no final."""
    _require(ride, RideState.COMPLETED)
    if ride.payment_method is not PaymentMethod.CASH:
        raise InvalidTransition("esta corrida foi paga por Pix antes de começar")
    ride.end_payment_confirmed = True


@dataclass
class PassengerAccount:
    passenger_id: str
    unpaid_cents: int = 0


def can_request(acc: PassengerAccount) -> bool:
    return acc.unpaid_cents == 0


def report_non_payment(ride: Ride, acc: PassengerAccount) -> None:
    _require(ride, RideState.COMPLETED)
    if ride.payment_method is not PaymentMethod.CASH or ride.end_payment_confirmed:
        raise InvalidTransition("não há pagamento pendente nesta corrida")
    acc.unpaid_cents += ride.price_cents


def settle_passenger_debt(acc: PassengerAccount, amount_cents: int) -> None:
    if amount_cents <= 0 or amount_cents > acc.unpaid_cents:
        raise ValueError("valor inválido para quitar a dívida do passageiro")
    acc.unpaid_cents -= amount_cents
