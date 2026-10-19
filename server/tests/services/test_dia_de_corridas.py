import datetime as dt

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_otp import FakeOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.clock import local_date
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.auth import AuthService, normalize_phone
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from app.services.riders import CannotGoOnline, RiderService
from app.services.sweeps import SweepService
from app.services.trips import TripService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import make_cpf

AGORA = 1_800_000_000.0


def test_um_dia_de_ponta_a_ponta_com_pix_dinheiro_bloqueio_e_entrada(session):
    provider, events, sender = FakePaymentProvider(), EventCollector(), FakeOtpSender()
    positions, maps = InMemoryPositionStore(), FakeMaps()
    auth, riders = AuthService(sender), RiderService(positions, events)
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), maps, payments, events)
    trips = TripService(payments, dispatch, events)
    quotes = QuoteService(maps, positions, InMemoryFactorStore())
    requests = RideRequestService(dispatch, events)
    sweeps = SweepService(payments, dispatch, trips, events)
    hoje = local_date(AGORA)

    def entrar(phone: str, role: str, t: float):
        auth.request_code(session, phone, t)
        return auth.verify_code(session, phone, sender.last_code(normalize_phone(phone)), role, "celular", t + 1)

    def pedir(passageiro, metodo: PaymentMethod, t: float):
        riders.report_position(rider.user_id, pt(300, 0), t - 1)
        quote = quotes.create_quote(session, passageiro.user_id, ORIGIN, pt(1500, 0), "Rua A", "Feira livre", t)
        ride = requests.request_ride(session, passageiro.user_id, quote.quote_id, metodo, t + 1)
        return dispatch.accept_offer(session, rider.user_id, ride.ride_id, t + 3)

    def percurso(ride, t: float):
        trips.arrive(session, rider.user_id, ride.ride_id, t)
        trips.confirm_helmet(session, rider.user_id, ride.ride_id, t + 1)
        trips.start_trip(session, rider.user_id, ride.ride_id, ride.pin, t + 5)
        trips.complete_trip(session, rider.user_id, ride.ride_id, t + 300)

    # 1) login do passageiro e do motoqueiro; cadastro e aprovação; motoqueiro fica disponível
    pax = entrar("75 99999-0001", "passenger", AGORA)
    rider = entrar("75 99999-0002", "rider", AGORA)
    assert pax.ok and rider.ok
    riders.register_rider(
        session, rider.user_id, name="Carlos Moto", cpf=make_cpf("123456789"), cnh_number="12345678901",
        plate="ABC1D23", moto_model="Honda CG 160", selfie_key="s", cnh_photo_key="c", crlv_key="m",
        cnh_expires_on=hoje + dt.timedelta(days=700), crlv_expires_on=hoje + dt.timedelta(days=300), today=hoje,
    )
    riders.approve(session, rider.user_id, AGORA + 5)
    riders.go_online(session, rider.user_id, hoje)

    # 2) corrida 1, Pix: pedido -> oferta -> aceite -> pago -> andamento -> avaliação
    ride1 = pedir(pax, PaymentMethod.PIX, AGORA + 10)
    assert ride1.state is RideState.ACCEPTED and ride1.fee_cents == 100
    charge1 = repo.get_current_charge_id(session, ride1.ride_id)
    assert payments.on_provider_event(session, provider.mark_paid(charge1)) == "applied"
    percurso(ride1, AGORA + 100)
    trips.rate(session, pax.user_id, ride1.ride_id, 5, AGORA + 500)
    assert queries.rider_card(session, rider.user_id).rating == 5.0
    preco1 = repo.get_ride(session, ride1.ride_id).price_cents

    # 3) corrida 2, dinheiro: passageiro não paga; passa o prazo; é bloqueado; paga atrasado pelo QR
    ride2 = pedir(pax, PaymentMethod.CASH, AGORA + 1000)
    percurso(ride2, AGORA + 1100)
    qr2 = repo.get_current_charge_id(session, ride2.ride_id)
    fim2 = AGORA + 1100 + 300
    assert sweeps.run(session, fim2 + 301).cash_blocked == 1
    assert repo.get_passenger_account(session, pax.user_id).unpaid_cents > 0
    with pytest.raises(NotAllowed, match="Falta pagar"):
        quotes.create_quote(session, pax.user_id, ORIGIN, pt(1500, 0), "A", "B", fim2 + 400)
    assert repo.get_rider_account(session, rider.user_id).cash_debt_cents == 0   # sem taxa no calote
    assert payments.on_provider_event(session, provider.mark_paid(qr2)) == "applied"
    assert repo.get_passenger_account(session, pax.user_id).unpaid_cents == 0
    preco2 = repo.get_ride(session, ride2.ride_id).price_cents

    # 4) corrida 3, dinheiro pago na mão: o motoqueiro confirma e a taxa vira dívida dele
    ride3 = pedir(pax, PaymentMethod.CASH, AGORA + 3000)
    percurso(ride3, AGORA + 3100)
    trips.confirm_cash_received(session, rider.user_id, ride3.ride_id, AGORA + 3500)
    assert repo.get_rider_account(session, rider.user_id).cash_debt_cents == 100
    assert repo.get_rider_account(session, rider.user_id).completed_rides == 3

    # 5) 10 corridas feitas: sem entrada não fica disponível; paga a entrada e volta
    acc = repo.get_rider_account(session, rider.user_id)
    acc.completed_rides = 10
    repo.save_rider_account(session, acc)
    with pytest.raises(CannotGoOnline) as erro:
        riders.go_online(session, rider.user_id, hoje)
    assert erro.value.code == "entry_pending"
    entrada = payments.start_entry_charge(session, rider.user_id)
    assert payments.on_provider_event(session, provider.mark_paid(entrada.charge_id)) == "applied"
    acc = repo.get_rider_account(session, rider.user_id)
    acc.cash_debt_cents = 0                      # a dívida de R$ 1,00 também bloqueia; quitada (a cobrança Pix dela é testada à parte)
    repo.save_rider_account(session, acc)
    riders.go_online(session, rider.user_id, hoje)

    # 6) fechamento do dia: o livro soma zero e bate com o extrato do provedor
    ledger = PgLedger(session)
    assert ledger.is_balanced() is True
    assert ledger.balance(f"rider:{rider.user_id}") == (preco1 - 100) + (preco2 - 100)
    assert ledger.balance(PgLedger.COMPANY) == 100 + 100 + 5000
    assert ledger.balance(PgLedger.PROVIDER) == -(preco1 + preco2 + 5000)
    extrato = {
        (f"entry:{c.rider_id}" if c.purpose == "entry" else f"charge:{c.charge_id}"): c.amount_cents
        for c in provider.charges.values()
        if c.paid and not c.refunded
    }
    assert ledger.reconcile(extrato) == {}
    tipos = {e.type for e in events.events}
    assert {"offer", "rider_accepted", "trip_completed", "passenger_blocked", "unblocked", "entry_paid"} <= tipos
