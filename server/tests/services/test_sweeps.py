from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.models import RideOfferRow, UserRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.payments import PaymentProviderError
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.sweeps import SweepReport, SweepService
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride, make_online_rider

AGORA = 1_800_000_000.0


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def w(positions, provider, events):
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    trips = TripService(payments, dispatch, events)
    sweeps = SweepService(payments, dispatch, trips, events)
    return SimpleNamespace(payments=payments, dispatch=dispatch, trips=trips, sweeps=sweeps, provider=provider)


def aceitar(session, positions, w, method=PaymentMethod.PIX, ride_id="ride-1", passenger_id="p1", rider_n=1, now=AGORA):
    if session.get(UserRow, passenger_id) is None:
        add_passenger(session, passenger_id, f"+5575900002{int(passenger_id[1:]):03d}")
    make_online_rider(session, positions, rider_n, pt(100 * rider_n, 0), now=now)
    add_searching_ride(session, ride_id, passenger_id, method=method, now=now)
    w.dispatch.offer_next(session, ride_id, now)
    return w.dispatch.accept_offer(session, f"r{rider_n}", ride_id, now + 1)


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_sem_nada_vencido_nada_acontece(w, session):
    relatorio = w.sweeps.run(session, AGORA)
    assert relatorio == SweepReport()      # tudo zerado e sem erros


def test_oferta_vencida_passa_para_a_proxima_moto(w, session, positions):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    make_online_rider(session, positions, 2, pt(200, 0), now=AGORA)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    assert w.sweeps.run(session, AGORA + 16).offers_expired == 1
    assert {o.rider_id: o.status for o in session.query(RideOfferRow)} == {"r1": "expired", "r2": "pending"}


def test_pix_nao_pago_em_2_minutos_cancela_e_libera_o_motoqueiro(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w)                       # Pix criado em AGORA + 1
    assert w.sweeps.run(session, AGORA + 120).pix_expired == 0
    relatorio = w.sweeps.run(session, AGORA + 1 + 120)
    assert relatorio.pix_expired == 1 and relatorio.errors == []
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert queries.rider_active_ride_id(session, "r1") is None
    assert "ride_cancelled" in tipos(events, "p1") and "ride_cancelled" in tipos(events, "r1")


def test_procura_desiste_depois_de_2_minutos_e_avisa_o_passageiro(w, session, events):
    add_passenger(session)
    add_searching_ride(session, now=AGORA)
    assert w.sweeps.run(session, AGORA + 119).searches_given_up == 0
    assert w.sweeps.run(session, AGORA + 121).searches_given_up == 1
    assert repo.get_ride(session, "ride-1").state is RideState.NO_RIDER
    assert "no_rider" in tipos(events, "p1")


def test_nao_desiste_enquanto_ha_oferta_pendente(w, session, positions):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA + 110)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA + 110)
    assert w.sweeps.run(session, AGORA + 121).searches_given_up == 0
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING


def test_fila_que_passa_de_8_minutos_volta_para_a_busca_com_outra_moto(w, session, positions):
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0")
    ride0 = repo.get_ride(session, "ride-0")
    ride0.state = RideState.IN_PROGRESS
    repo.save_ride(session, ride0)
    repo.set_ride_details(session, "ride-0", repo.RideDetails(pt(0, 0), pt(300, 0), "A", "B", 400, 1.0, ""))
    positions.update("r1", pt(150, 0), now=AGORA + 100)
    # corrida da fila em dinheiro: uma da fila em Pix venceria antes (o passageiro tem 2 minutos para pagar)
    add_searching_ride(session, "ride-1", "p1", method=PaymentMethod.CASH, now=AGORA + 100)
    w.dispatch.offer_next(session, "ride-1", AGORA + 100)
    w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101)
    assert repo.get_ride(session, "ride-1").state is RideState.QUEUED
    make_online_rider(session, positions, 2, pt(120, 0), now=AGORA + 101 + 480)
    positions.update("r1", pt(150, 0), now=AGORA + 101 + 480)
    relatorio = w.sweeps.run(session, AGORA + 101 + 480)
    assert relatorio.queue_released == 1
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
    assert queries.get_pending_offer(session, "ride-1").rider_id == "r2"


def test_espera_na_chegada_de_5_minutos_cancela_com_devolucao_do_pix(w, session, positions, provider, events):
    add_passenger(session)
    aceitar(session, positions, w)
    charge_id = repo.get_current_charge_id(session, "ride-1")
    w.payments.on_provider_event(session, provider.mark_paid(charge_id))
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    assert w.sweeps.run(session, AGORA + 50 + 299).arrival_cancelled == 0
    relatorio = w.sweeps.run(session, AGORA + 50 + 300)
    assert relatorio.arrival_cancelled == 1
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert provider.charges[charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    tipo, dados = repo.ride_events(session, "ride-1")[-1]
    assert tipo == "cancelled" and dados["by"] == "timeout" and dados["compensation_cents"] == 200


def test_pagamento_em_dinheiro_nao_confirmado_bloqueia_o_passageiro(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    w.trips.confirm_helmet(session, "r1", "ride-1", AGORA + 51)
    w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 52)
    w.trips.complete_trip(session, "r1", "ride-1", AGORA + 400)
    assert w.sweeps.run(session, AGORA + 699).cash_blocked == 0
    assert w.sweeps.run(session, AGORA + 700).cash_blocked == 1
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 700
    assert w.sweeps.run(session, AGORA + 800).cash_blocked == 0


def test_erro_em_uma_corrida_nao_trava_as_outras(session, positions, provider, events):
    class DespachanteQuebrado(DispatchService):
        def offer_next(self, session, ride_id, now):
            if ride_id == "ride-1":
                raise RuntimeError("falha de teste")
            return super().offer_next(session, ride_id, now)

    payments = PaymentService(provider, events=events)
    dispatch = DespachanteQuebrado(positions, ReservationBook(), FakeMaps(), payments, events)
    sweeps = SweepService(payments, dispatch, TripService(payments, dispatch, events), events)
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-1", "p1", now=AGORA)
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    relatorio = sweeps.run(session, AGORA + 121)
    assert len(relatorio.errors) == 1 and "ride-1" in relatorio.errors[0]
    assert repo.get_ride(session, "ride-2").state is RideState.NO_RIDER
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING


def test_aviso_de_etapa_desfeita_nao_fica_no_coletor(session, positions, provider, events):
    # Revisão final do plano 2B (I3): o banco volta atrás, os avisos já anotados também.
    class ViagensQuebradas(TripService):
        def after_ride_ends(self, session, rider_id, now):
            raise RuntimeError("falha de teste")

    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    sweeps = SweepService(payments, dispatch, ViagensQuebradas(payments, dispatch, events), events)
    add_passenger(session)
    aceitar(session, positions, SimpleNamespace(dispatch=dispatch))      # Pix que ninguém paga
    events.drain()
    relatorio = sweeps.run(session, AGORA + 1 + 120)
    assert len(relatorio.errors) == 1 and "ride-1" in relatorio.errors[0]
    assert repo.get_ride(session, "ride-1").state is RideState.ACCEPTED
    assert events.events == ()


class ProvedorInstavel(FakePaymentProvider):
    fora = True

    def create_pix_charge(self, *args, **kwargs):
        if self.fora:
            raise PaymentProviderError("Woovi fora do ar")
        return super().create_pix_charge(*args, **kwargs)


def test_qr_que_faltou_e_criado_depois_e_o_passageiro_ganha_um_prazo_novo(session, positions, events):
    # Revisão final do plano 2B (I4): sem QR o passageiro não tinha como pagar pelo Pix, então não pode ser bloqueado.
    provider = ProvedorInstavel()
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    trips = TripService(payments, dispatch, events)
    sweeps = SweepService(payments, dispatch, trips, events)
    w = SimpleNamespace(payments=payments, dispatch=dispatch, trips=trips, provider=provider)
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    trips.arrive(session, "r1", "ride-1", AGORA + 50)
    trips.confirm_helmet(session, "r1", "ride-1", AGORA + 51)
    trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 52)
    trips.complete_trip(session, "r1", "ride-1", AGORA + 400)           # provedor fora: sem QR
    fim = AGORA + 400
    relatorio = sweeps.run(session, fim + 301)
    assert relatorio.cash_blocked == 0 and relatorio.qr_created == 0 and len(relatorio.errors) == 1
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 0
    provider.fora = False
    assert sweeps.run(session, fim + 310).qr_created == 1
    charge = repo.get_charge(session, repo.get_current_charge_id(session, "ride-1"))
    assert charge.purpose == "end" and "qr_ready" in [e.type for e in events.events if e.user_id == "p1"]
    assert sweeps.run(session, fim + 310 + 299).cash_blocked == 0       # o prazo de 5 minutos recomeça no QR
    assert sweeps.run(session, fim + 310 + 300).cash_blocked == 1

