from app.adapters.fake_maps import StraightLineEta
from app.adapters.fake_payments import FakePaymentProvider
from app.domain.dispatch import RiderStatus, rank_candidates
from app.domain.fees import (
    RiderAccount,
    can_receive_offers,
    fee_for_ride,
    register_completed_ride,
)
from app.domain.ledger import Ledger
from app.domain.payments import ProcessedEvents, compute_split, settle_pix_ride
from app.domain.pricing import final_price_cents, smooth_factor, target_factor
from app.domain.rides import (
    Ride,
    RideState,
    accept,
    complete,
    confirm_helmet,
    confirm_pix_paid,
    mark_arrived,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod
from tests.helpers import ORIGIN, pt


def test_corrida_pix_completa_fecha_as_contas():
    # preço pelo movimento do momento
    factor = smooth_factor(1.0, target_factor(pending_requests=3, free_riders=3))
    price = final_price_cents(distance_m=2000, factor=factor)
    assert price == 600
    fee = fee_for_ride(1)
    assert fee == 100

    # escolha da moto
    riders = [RiderStatus("rider-1", pt(200, 0)), RiderStatus("rider-2", pt(900, 0))]
    best = rank_candidates(riders, ORIGIN, StraightLineEta())[0]
    assert best.rider_id == "rider-1"
    assert best.will_queue is False

    # corrida: aceita, Pix pago, chega, capacete, código, termina
    acc = RiderAccount("rider-1")
    assert can_receive_offers(acc)
    ride = Ride("ride-1", "p1", price, PaymentMethod.PIX, pin="4821")
    start_search(ride, 0)
    accept(ride, best.rider_id, now=10, rider_busy=False)

    provider = FakePaymentProvider()
    split = settle_pix_ride(acc, price, fee)
    charge = provider.create_pix_charge(ride.ride_id, best.rider_id, price, split)
    event = provider.mark_paid(charge.charge_id)
    events = ProcessedEvents()
    assert events.first_time(event["event_id"]) is True
    confirm_pix_paid(ride)

    ledger = Ledger()
    ledger.post_ride_payment(ride.ride_id, best.rider_id, price, split)

    mark_arrived(ride, 100)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    register_completed_ride(acc, PaymentMethod.PIX, fee)

    assert ride.state is RideState.COMPLETED
    assert acc.completed_rides == 1
    assert ledger.balance("rider:rider-1") == 500
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -600
    assert ledger.is_balanced() is True
    assert ledger.reconcile({"ride:ride-1": 600}) == {}

    # o provedor repete o aviso: nada é contado duas vezes
    assert events.first_time(event["event_id"]) is False


def test_corrida_em_dinheiro_gera_divida_que_a_proxima_corrida_pix_abate():
    acc = RiderAccount("rider-1")
    fee = fee_for_ride(1)
    register_completed_ride(acc, PaymentMethod.CASH, fee)
    assert acc.cash_debt_cents == 100

    price = 700
    split = settle_pix_ride(acc, price, fee_for_ride(2))
    assert split.debt_paid_cents == 100
    assert split.rider_cents == 500
    assert split.company_cents == 200
    assert acc.cash_debt_cents == 0

    ledger = Ledger()
    ledger.post_ride_payment("ride-2", "rider-1", price, split)
    assert ledger.is_balanced() is True
    assert compute_split(price, 100, 0).rider_cents == 600
