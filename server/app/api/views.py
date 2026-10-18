"""Como a corrida aparece para cada lado. Só monta dicionários a partir do banco; não decide nada."""
from __future__ import annotations

from app.db import queries
from app.db import repositories as repo
from app.domain.rides import Ride, RideState
from app.domain.types import PaymentMethod
from app.runtime import Unit
from app.services.quotes import Quote, passenger_block_reason

_WITH_RIDER_ON_THE_MOVE = (RideState.ACCEPTED, RideState.ARRIVED, RideState.IN_PROGRESS)


def place(lat: float, lng: float, text: str) -> dict:
    return {"lat": lat, "lng": lng, "text": text}


def quote_view(quote: Quote, payment_methods: list[str]) -> dict:
    return {
        "quote_id": quote.quote_id, "price_cents": quote.price_cents, "distance_m": quote.distance_m,
        "duration_s": quote.duration_s, "reason": quote.reason, "expires_at": quote.expires_at,
        "pickup": place(quote.pickup.lat, quote.pickup.lng, quote.pickup_text),
        "destination": place(quote.destination.lat, quote.destination.lng, quote.destination_text),
        "eta_seconds": quote.eta_seconds, "nearby_riders": quote.nearby_riders,
        "payment_methods": payment_methods,
    }


def _pix_to_pay(unit: Unit, ride: Ride) -> dict | None:
    """Pix de antes da corrida que o passageiro ainda não pagou: o que ele precisa para pagar."""
    if ride.payment_method is not PaymentMethod.PIX or ride.pix_paid or ride.pix_charge_created_at is None:
        return None
    if ride.state not in (RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED):
        return None
    charge_id = repo.get_current_charge_id(unit.session, ride.ride_id)
    if charge_id is None:
        return None
    return {
        "charge_id": charge_id, "amount_cents": repo.get_charge(unit.session, charge_id).amount_cents,
        "expires_at": ride.pix_charge_created_at + unit.cfg.rides.pix_window_s,
    }


def _end_payment(unit: Unit, ride: Ride) -> dict | None:
    """Corrida em dinheiro já terminada e ainda sem pagamento confirmado (QR do fim da corrida)."""
    if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
        return None
    if ride.end_payment_confirmed:
        return None
    return {
        "charge_id": repo.get_current_charge_id(unit.session, ride.ride_id),
        "amount_cents": ride.price_cents, "blocked": ride.non_payment_reported,
    }


def passenger_ride_view(unit: Unit, ride_id: str) -> dict:
    ride = repo.get_ride(unit.session, ride_id)
    details = repo.get_ride_details(unit.session, ride_id)
    rider = None
    position = None
    if ride.rider_id is not None:
        card = queries.rider_card(unit.session, ride.rider_id)
        rider = {
            "rider_id": card.rider_id, "name": card.name, "plate": card.plate, "moto_model": card.moto_model,
            "rating": card.rating, "rating_count": card.rating_count,
            "photo_url": f"/v1/riders/{card.rider_id}/documents/selfie" if card.selfie_key else None,
        }
        if ride.state in _WITH_RIDER_ON_THE_MOVE:
            found = unit.positions.get(ride.rider_id)
            position = None if found is None else {"lat": found.lat, "lng": found.lng}
    return {
        "ride_id": ride.ride_id, "state": ride.state.value, "queued": ride.state is RideState.QUEUED,
        "price_cents": ride.price_cents, "price_reason": details.price_reason, "method": ride.payment_method.value,
        "pin": ride.pin, "helmet_confirmed": ride.helmet_confirmed, "pix_paid": ride.pix_paid,
        "pickup": place(details.pickup.lat, details.pickup.lng, details.pickup_text),
        "destination": place(details.destination.lat, details.destination.lng, details.destination_text),
        "distance_m": details.distance_m, "rider": rider, "rider_position": position,
        "pay": _pix_to_pay(unit, ride), "end_payment": _end_payment(unit, ride),
    }


def passenger_state(unit: Unit, passenger_id: str, payment_methods: list[str]) -> dict:
    session = unit.session
    open_id = queries.passenger_open_ride_id(session, passenger_id)
    unpaid_id = queries.passenger_unpaid_cash_ride_id(session, passenger_id)
    pending = None
    if unpaid_id is not None:
        unpaid = repo.get_ride(session, unpaid_id)
        pending = {
            "ride_id": unpaid_id, "amount_cents": unpaid.price_cents,
            "charge_id": repo.get_current_charge_id(session, unpaid_id), "blocked": unpaid.non_payment_reported,
        }
    contact = repo.get_emergency_contact(session, passenger_id)
    return {
        "ride": passenger_ride_view(unit, open_id) if open_id else None,
        "pending_payment": pending,
        "blocked_reason": None if open_id else passenger_block_reason(session, passenger_id),
        "unpaid_cents": repo.get_passenger_account(session, passenger_id).unpaid_cents,
        "emergency_contact": None if contact is None else {"name": contact.name, "phone": contact.phone},
        "payment_methods": payment_methods,
    }
