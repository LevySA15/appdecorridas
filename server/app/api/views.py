"""Como a corrida aparece para cada lado. Só monta dicionários a partir do banco; não decide nada."""
from __future__ import annotations

from app.db import queries
from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from app.domain.fees import offer_block_reason
from app.domain.rides import Ride, RideState
from app.domain.types import PaymentMethod
from app.runtime import Unit
from app.services.dispatch import offer_payload
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
        rider = queries.rider_card(unit.session, ride.rider_id).public()
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
        "queue": queries.queue_info(unit.session, ride.ride_id, ride.rider_id) if ride.state is RideState.QUEUED else None,
        "safety_alert": queries.open_safety_alert(unit.session, ride.ride_id),
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


# --- motoqueiro ----------------------------------------------------------------------------------------


def rider_ride_view(unit: Unit, ride_id: str) -> dict:
    ride = repo.get_ride(unit.session, ride_id)
    details = repo.get_ride_details(unit.session, ride_id)
    passenger = unit.session.get(UserRow, ride.passenger_id)
    first_name = (passenger.name.split() or [""])[0] if passenger is not None else ""
    return {
        "ride_id": ride.ride_id, "state": ride.state.value, "queued": ride.state is RideState.QUEUED,
        "price_cents": ride.price_cents, "fee_cents": ride.fee_cents, "method": ride.payment_method.value,
        "pix_paid": ride.pix_paid, "helmet_confirmed": ride.helmet_confirmed,
        "passenger": {"name": first_name},      # o motoqueiro só vê o primeiro nome (o código fica com o passageiro)
        "pickup": place(details.pickup.lat, details.pickup.lng, details.pickup_text),
        "destination": place(details.destination.lat, details.destination.lng, details.destination_text),
        "distance_m": details.distance_m, "end_payment": _end_payment(unit, ride),
    }


def rider_state(unit: Unit, rider_id: str) -> dict:
    session = unit.session
    profile = session.get(RiderProfileRow, rider_id)
    if profile is None:
        return {
            "registration": {"status": "not_registered"}, "account": None, "offer": None, "ride": None,
            "queued_ride": None, "awaiting_payment": None,
        }
    fees = unit.cfg.fees
    account = repo.get_rider_account(session, rider_id)
    rating = round(profile.rating_sum / profile.rating_count, 1) if profile.rating_count else None
    offer_row = queries.pending_offer_for_rider(session, rider_id)
    offer = None
    if offer_row is not None:
        ride = repo.get_ride(session, offer_row.ride_id)
        offer = offer_payload(
            ride, repo.get_ride_details(session, offer_row.ride_id), eta_seconds=offer_row.eta_seconds,
            will_queue=offer_row.will_queue, expires_at=offer_row.expires_at,
        )
    active_id = queries.rider_active_ride_id(session, rider_id)
    queued_id = queries.queued_ride_id_of_rider(session, rider_id)
    unpaid_id = queries.rider_unpaid_cash_ride_id(session, rider_id)
    return {
        "registration": {
            "status": profile.status, "online": profile.online, "reason": profile.rejected_reason,
            "rating": rating, "rating_count": profile.rating_count,
            "cnh_expires_on": profile.cnh_expires_on.isoformat() if profile.cnh_expires_on else None,
            "crlv_expires_on": profile.crlv_expires_on.isoformat() if profile.crlv_expires_on else None,
        },
        "account": {
            "completed_rides": account.completed_rides, "trial_rides": fees.trial_rides,
            "entry_paid": account.entry_paid, "entry_fee_cents": fees.entry_fee_cents,
            "needs_entry": offer_block_reason(account, fees) is not None,
            "cash_debt_cents": account.cash_debt_cents, "cash_debt_limit_cents": fees.cash_debt_limit_cents,
        },
        "offer": offer,
        "ride": rider_ride_view(unit, active_id) if active_id else None,
        "queued_ride": rider_ride_view(unit, queued_id) if queued_id else None,
        "awaiting_payment": rider_ride_view(unit, unpaid_id) if unpaid_id else None,
    }
