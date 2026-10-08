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
from app.domain.payments import (
    ProcessedEvents,
    compute_split,
    confirm_charge_debt,
    release_charge_debt,
    reserve_pix_split,
    restore_charge_debt,
)
from app.domain.pricing import final_price_cents, smooth_factor, target_factor
from app.domain.rides import (
    Ride,
    RideState,
    accept,
    cancel,
    cancel_unpaid_pix,
    complete,
    confirm_helmet,
    confirm_pix_paid,
    mark_arrived,
    on_pix_paid,
    pix_window_expired,
    release_from_queue,
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
    split = reserve_pix_split(acc, price, fee)
    charge = provider.create_pix_charge(ride.ride_id, best.rider_id, price, split)
    event = provider.mark_paid(charge.charge_id)
    events = ProcessedEvents()
    assert events.first_time(event["event_id"]) is True
    confirm_charge_debt(acc, charge)
    confirm_pix_paid(ride)

    ledger = Ledger()
    ledger.post_charge_payment(charge.charge_id, best.rider_id, price, split)

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
    assert ledger.reconcile({"charge:ch-1": 600}) == {}

    # o provedor repete o aviso: nada é contado duas vezes
    assert events.first_time(event["event_id"]) is False


def test_corrida_em_dinheiro_gera_divida_que_a_proxima_corrida_pix_abate():
    acc = RiderAccount("rider-1")
    fee = fee_for_ride(1)
    register_completed_ride(acc, PaymentMethod.CASH, fee)
    assert acc.cash_debt_cents == 100

    price = 700
    split = reserve_pix_split(acc, price, fee_for_ride(2))
    assert split.debt_paid_cents == 100
    assert split.rider_cents == 500
    assert split.company_cents == 200
    assert acc.cash_debt_cents == 100  # a divida so cai quando o Pix for pago
    provider = FakePaymentProvider()
    charge = provider.create_pix_charge("ride-2", "rider-1", price, split)
    provider.mark_paid(charge.charge_id)
    confirm_charge_debt(acc, charge)
    assert acc.cash_debt_cents == 0

    ledger = Ledger()
    ledger.post_charge_payment(charge.charge_id, "rider-1", price, split)
    assert ledger.is_balanced() is True
    assert compute_split(price, 100, 0).rider_cents == 600


def test_pix_que_vence_sem_pagar_nao_perdoa_a_divida_do_motoqueiro():
    acc = RiderAccount("rider-1", cash_debt_cents=1000)
    ride = Ride("ride-1", "p1", 700, PaymentMethod.PIX, pin="4821")
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=False)
    charge = FakePaymentProvider().create_pix_charge(
        "ride-1", "rider-1", 700, reserve_pix_split(acc, 700, 100)
    )
    assert pix_window_expired(ride, 130) is True
    cancel_unpaid_pix(ride)
    release_charge_debt(acc, charge)
    assert acc.cash_debt_cents == 1000
    assert acc.debt_reserved_cents == 0


def test_corrida_cancelada_depois_de_paga_devolve_o_dinheiro_e_a_divida():
    provider = FakePaymentProvider()
    ledger = Ledger()
    acc = RiderAccount("rider-1", cash_debt_cents=1000)
    ride = Ride("ride-1", "p1", 700, PaymentMethod.PIX, pin="4821")
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=False)
    charge = provider.create_pix_charge("ride-1", "rider-1", 700, reserve_pix_split(acc, 700, 100))
    provider.mark_paid(charge.charge_id)
    confirm_charge_debt(acc, charge)
    ledger.post_charge_payment(charge.charge_id, "rider-1", 700, charge.split)
    assert on_pix_paid(ride) is False
    assert acc.cash_debt_cents == 700

    result = cancel(ride, now=20)
    assert result.refund_needed is True
    provider.refund(charge.charge_id)
    ledger.post_refund(charge.charge_id)
    restore_charge_debt(acc, charge)

    assert acc.cash_debt_cents == 1000
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.is_balanced() is True


def test_corrida_na_fila_paga_volta_para_a_busca_e_e_paga_de_novo_por_outra_moto():
    provider = FakePaymentProvider()
    ledger = Ledger()
    acc1 = RiderAccount("rider-1", cash_debt_cents=300)
    ride = Ride("ride-1", "p1", 700, PaymentMethod.PIX, pin="4821")
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    charge1 = provider.create_pix_charge("ride-1", "rider-1", 700, reserve_pix_split(acc1, 700, 100))
    provider.mark_paid(charge1.charge_id)
    confirm_charge_debt(acc1, charge1)
    ledger.post_charge_payment(charge1.charge_id, "rider-1", 700, charge1.split)
    assert on_pix_paid(ride) is False

    assert release_from_queue(ride, now=500) is True  # há Pix pago para estornar
    provider.refund(charge1.charge_id)
    ledger.post_refund(charge1.charge_id)
    restore_charge_debt(acc1, charge1)
    assert acc1.cash_debt_cents == 300

    acc2 = RiderAccount("rider-2")
    accept(ride, "rider-2", now=510, rider_busy=False)
    charge2 = provider.create_pix_charge("ride-1", "rider-2", 700, reserve_pix_split(acc2, 700, 100))
    provider.mark_paid(charge2.charge_id)
    confirm_charge_debt(acc2, charge2)
    ledger.post_charge_payment(charge2.charge_id, "rider-2", 700, charge2.split)
    assert on_pix_paid(ride) is False

    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance("rider:rider-2") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.is_balanced() is True
