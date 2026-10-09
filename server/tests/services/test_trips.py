import datetime as dt
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.models import RideOfferRow, RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.rides import CancelResult, InvalidTransition, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.riders import CannotGoOnline, RiderService
from app.services.trips import AlreadyRated, NotYourRide, TripService
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
def reservas():
    return ReservationBook()


@pytest.fixture()
def w(positions, reservas, provider, events):
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, reservas, FakeMaps(), payments, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, trips=TripService(payments, dispatch, events), provider=provider
    )


def aceitar(session, positions, w, method=PaymentMethod.PIX, ride_id="ride-1", passenger_id="p1", rider_n=1,
            destination=None, now=AGORA):
    """Corrida pedida, oferecida e aceita pelo motoqueiro `r<rider_n>`."""
    rider_id = f"r{rider_n}"
    if session.get(RiderProfileRow, rider_id) is None:
        make_online_rider(session, positions, rider_n, pt(100 * rider_n, 0), now=now)
    add_searching_ride(session, ride_id, passenger_id, method=method, destination=destination, now=now)
    assert w.dispatch.offer_next(session, ride_id, now) == rider_id
    return w.dispatch.accept_offer(session, rider_id, ride_id, now + 4)


def pagar(session, w, ride_id="ride-1"):
    charge_id = repo.get_current_charge_id(session, ride_id)
    assert w.payments.on_provider_event(session, w.provider.mark_paid(charge_id)) == "applied"


def ate_o_fim(session, w, rider_id="r1", ride_id="ride-1", t=AGORA + 100):
    ride = repo.get_ride(session, ride_id)
    w.trips.arrive(session, rider_id, ride_id, t)
    w.trips.confirm_helmet(session, rider_id, ride_id, t + 1)
    w.trips.start_trip(session, rider_id, ride_id, ride.pin, t + 5)
    w.trips.complete_trip(session, rider_id, ride_id, t + 400)


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_corrida_pix_do_aceite_ao_fim(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w)
    pagar(session, w)
    ate_o_fim(session, w)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.COMPLETED and ride.completed_at == AGORA + 500
    assert repo.get_rider_account(session, "r1").completed_rides == 1
    assert [k for k, _ in repo.ride_events(session, "ride-1")] == [
        "offered", "accepted", "arrived", "helmet_confirmed", "started", "completed",
    ]
    fim = next(e for e in events.events if e.type == "trip_completed" and e.user_id == "p1")
    assert fim.payload["pay"] is None and fim.payload["price_cents"] == 700
    assert {"rider_arrived", "trip_started"} <= set(tipos(events, "p1"))


def test_nao_inicia_sem_capacete_sem_pix_ou_com_codigo_errado(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w)
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    with pytest.raises(InvalidTransition, match="capacete"):
        w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 51)
    w.trips.confirm_helmet(session, "r1", "ride-1", AGORA + 52)
    with pytest.raises(InvalidTransition, match="Pix"):
        w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 53)
    pagar(session, w)
    ride = repo.get_ride(session, "ride-1")
    assert ride.helmet_confirmed is True
    with pytest.raises(ValueError, match="código"):
        w.trips.start_trip(session, "r1", "ride-1", "0000", AGORA + 53)
    w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 54)
    assert repo.get_ride(session, "ride-1").state is RideState.IN_PROGRESS


def test_so_o_motoqueiro_da_corrida_mexe_nela(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w)
    make_online_rider(session, positions, 2, pt(900, 0), now=AGORA)
    with pytest.raises(NotYourRide):
        w.trips.arrive(session, "r2", "ride-1", AGORA + 50)
    with pytest.raises(NotYourRide):
        w.trips.cancel_by_passenger(session, "p-outro", "ride-1", AGORA + 50)


def test_corrida_em_dinheiro_ao_terminar_gera_o_qr_e_ainda_nao_cobra_taxa(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    charge = repo.get_charge(session, repo.get_current_charge_id(session, "ride-1"))
    assert charge.purpose == "end" and charge.amount_cents == 700
    for dono in ("p1", "r1"):
        aviso = next(e for e in events.events if e.type == "trip_completed" and e.user_id == dono)
        assert aviso.payload["pay"]["charge_id"] == charge.charge_id
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 0


def test_motoqueiro_confirma_dinheiro_recebido_pelo_servico_de_corridas(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    make_online_rider(session, positions, 2, pt(900, 0), now=AGORA)
    with pytest.raises(NotYourRide):
        w.trips.confirm_cash_received(session, "r2", "ride-1", AGORA + 600)
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100


def test_cancelar_em_procura_retira_a_oferta_e_solta_a_moto(w, session, positions, events, reservas):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 3) == CancelResult(0, False)
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert session.query(RideOfferRow).one().status == "expired"
    assert reservas.reserve("r1", "ride-qualquer") is True
    assert "offer_expired" in tipos(events, "r1")


def test_cancelar_depois_do_prazo_gratis_registra_a_compensacao(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)           # aceita em AGORA + 4
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 4 + 61)
    assert resultado == CancelResult(200, False)
    tipo, dados = repo.ride_events(session, "ride-1")[-1]
    assert tipo == "cancelled" and dados["compensation_cents"] == 200 and dados["by"] == "passenger"


def test_cancelar_dentro_do_prazo_gratis_nao_tem_compensacao(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 4 + 30) == CancelResult(0, False)


def test_cancelar_corrida_paga_devolve_o_pix_e_libera_o_motoqueiro(w, session, positions, provider, events):
    add_passenger(session)
    aceitar(session, positions, w)
    pagar(session, w)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 10)
    assert resultado.refund_needed is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert queries.rider_active_ride_id(session, "r1") is None
    assert "ride_cancelled" in tipos(events, "r1")


def _com_corrida_na_fila(session, positions, w, pagar_a_da_fila=False):
    """r1 está terminando a corrida ride-0 (dinheiro) e aceitou ride-1 (Pix) para a fila."""
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0",
            destination=pt(300, 0))
    w.trips.arrive(session, "r1", "ride-0", AGORA + 50)
    w.trips.confirm_helmet(session, "r1", "ride-0", AGORA + 51)
    w.trips.start_trip(session, "r1", "ride-0", "4821", AGORA + 52)
    positions.update("r1", pt(150, 0), now=AGORA + 100)     # a 150 m do destino: "terminando"
    add_searching_ride(session, "ride-1", "p1", now=AGORA + 100)
    assert w.dispatch.offer_next(session, "ride-1", AGORA + 100) == "r1"
    ride = w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101)
    assert ride.state is RideState.QUEUED
    if pagar_a_da_fila:
        pagar(session, w, "ride-1")


def test_ao_terminar_o_motoqueiro_assume_a_corrida_da_fila(w, session, positions, events):
    _com_corrida_na_fila(session, positions, w)
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.ACCEPTED and ride.en_route_since == AGORA + 400
    assert "rider_on_the_way" in tipos(events, "p1") and "next_ride" in tipos(events, "r1")
    assert "promoted" in [k for k, _ in repo.ride_events(session, "ride-1")]


def test_10a_corrida_sem_entrada_devolve_a_da_fila_para_a_busca_e_reoferece(w, session, positions, events, provider):
    # Review Focus 3 (rede de segurança: a contagem chegou a 10 depois de a fila ter sido aceita)
    _com_corrida_na_fila(session, positions, w, pagar_a_da_fila=True)
    make_online_rider(session, positions, 2, pt(120, 0), now=AGORA + 380)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.SEARCHING and ride.rider_id is None
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert PgLedger(session).balance("rider:r1") == 0           # o Pix da fila foi devolvido
    assert queries.get_pending_offer(session, "ride-1").rider_id == "r2"
    assert "queue_released" in tipos(events, "p1")
    with pytest.raises(CannotGoOnline) as erro:
        RiderService(positions, events).go_online(session, "r1", dt.date(2027, 1, 15))
    assert erro.value.code == "entry_pending"


def test_depois_de_terminar_o_motoqueiro_ocupado_nao_pega_a_fila_ainda(w, session, positions):
    _com_corrida_na_fila(session, positions, w)
    w.trips.after_ride_ends(session, "r1", AGORA + 200)   # ride-0 ainda está em andamento
    assert repo.get_ride(session, "ride-1").state is RideState.QUEUED


def test_avaliacao_atualiza_a_nota_do_motoqueiro(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    w.trips.rate(session, "p1", "ride-1", 5, AGORA + 600)
    ficha = queries.rider_card(session, "r1")
    assert (ficha.rating, ficha.rating_count) == (5.0, 1)
    w.trips.rate(session, "r1", "ride-1", 3, AGORA + 601)         # o motoqueiro avalia o passageiro
    assert queries.rider_card(session, "r1").rating_count == 1


def test_avaliacao_recusa_repetida_antes_do_fim_fora_da_faixa_e_de_estranho(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="depois que a corrida acaba"):
        w.trips.rate(session, "p1", "ride-1", 5, AGORA + 10)
    ate_o_fim(session, w)
    for ruim in (0, 6):
        with pytest.raises(ValueError, match="1 a 5"):
            w.trips.rate(session, "p1", "ride-1", ruim, AGORA + 600)
    with pytest.raises(NotYourRide):
        w.trips.rate(session, "p-estranho", "ride-1", 5, AGORA + 600)
    w.trips.rate(session, "p1", "ride-1", 4, AGORA + 600)
    with pytest.raises(AlreadyRated):
        w.trips.rate(session, "p1", "ride-1", 5, AGORA + 601)
    assert queries.rider_card(session, "r1").rating_count == 1
