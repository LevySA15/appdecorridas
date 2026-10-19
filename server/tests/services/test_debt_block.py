"""O motoqueiro que deve a taxa das corridas em dinheiro tem uma corrida de folga e depois é bloqueado."""
import datetime as dt
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService, OfferGone
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.riders import CannotGoOnline, RiderService
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride
from tests.services.test_trips import AGORA, _com_corrida_na_fila, aceitar, ate_o_fim, pagar

HOJE = dt.date(2027, 1, 15)


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
    payments = PaymentService(provider, events=events, positions=positions)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, provider=provider,
        trips=TripService(payments, dispatch, events, positions=positions),
        riders=RiderService(positions, events),
    )


def eventos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]


def online(session, rider_id="r1") -> bool:
    return session.get(RiderProfileRow, rider_id).online


def corrida_em_dinheiro_terminada(session, positions, w):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)


def test_confirmar_dinheiro_que_cruza_o_limite_poe_o_motoqueiro_em_nao_estou_e_avisa(session, positions, w, events):
    corrida_em_dinheiro_terminada(session, positions, w)
    assert online(session) is True and positions.get("r1") is not None
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100
    assert online(session) is False and positions.get("r1") is None
    assert eventos(events, "r1", "debt_required") == [{"cash_debt_cents": 100, "debt_limit_cents": 70}]


def test_a_primeira_corrida_em_dinheiro_e_a_de_folga(session, positions, w):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)       # sem dívida: pode aceitar
    ate_o_fim(session, w)
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", method=PaymentMethod.PIX, now=AGORA + 700)
    assert w.dispatch.offer_next(session, "ride-2", AGORA + 700) is None        # a segunda: nenhuma oferta, nem em Pix


def test_motoqueiro_que_acabou_de_ficar_bloqueado_nao_aceita_a_oferta_que_tinha(session, positions, w):
    corrida_em_dinheiro_terminada(session, positions, w)
    add_passenger(session, "p2", "+5575900000012")
    positions.update("r1", pt(100, 0), AGORA + 450)
    add_searching_ride(session, "ride-2", "p2", method=PaymentMethod.PIX, now=AGORA + 450)
    assert w.dispatch.offer_next(session, "ride-2", AGORA + 450) == "r1"          # oferta feita antes do bloqueio
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 460)
    with pytest.raises(OfferGone):
        w.dispatch.accept_offer(session, "r1", "ride-2", AGORA + 462)


def test_corrida_em_andamento_segue_e_ao_acabar_o_motoqueiro_fica_em_nao_estou(session, positions, w, events):
    corrida_em_dinheiro_terminada(session, positions, w)                        # ride-1 terminada, dinheiro por confirmar
    add_passenger(session, "p2", "+5575900000012")
    positions.update("r1", pt(100, 0), AGORA + 450)
    add_searching_ride(session, "ride-2", "p2", method=PaymentMethod.CASH, now=AGORA + 450)
    w.dispatch.offer_next(session, "ride-2", AGORA + 450)
    w.dispatch.accept_offer(session, "r1", "ride-2", AGORA + 455)
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 460)           # durante a corrida 2
    assert repo.get_ride(session, "ride-2").state is RideState.ACCEPTED           # a corrida em andamento não cai
    assert online(session) is True and eventos(events, "r1", "debt_required") != []
    ate_o_fim(session, w, ride_id="ride-2", t=AGORA + 500)
    assert online(session) is False


def test_corrida_da_fila_volta_para_a_busca_com_devolucao_do_pix_quando_ha_divida(session, positions, w, events):
    _com_corrida_na_fila(session, positions, w, pagar_a_da_fila=True)
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 100
    repo.save_rider_account(session, acc)
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
    assert PgLedger(session).balance("rider:r1") == 0                           # o Pix da fila foi devolvido
    assert online(session) is False
    assert eventos(events, "r1", "debt_required") == [{"cash_debt_cents": 100, "debt_limit_cents": 70}]
    assert eventos(events, "r1", "entry_required") == []
    motivo = [d for k, d in repo.ride_events(session, "ride-1") if k == "queue_released"][0]["reason"]
    assert motivo == "dívida pendente"


def test_ficar_disponivel_com_divida_diz_quanto_deve_e_o_codigo_debt_pending(session, positions, w):
    corrida_em_dinheiro_terminada(session, positions, w)
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)
    with pytest.raises(CannotGoOnline) as erro:
        w.riders.go_online(session, "r1", HOJE)
    assert erro.value.code == "debt_pending" and "R$ 1,00" in erro.value.message


def test_ficar_disponivel_com_entrada_pendente_continua_entry_pending(session, positions, w):
    corrida_em_dinheiro_terminada(session, positions, w)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides, acc.cash_debt_cents = 10, 100                            # deve a entrada e a taxa
    repo.save_rider_account(session, acc)
    with pytest.raises(CannotGoOnline) as erro:
        w.riders.go_online(session, "r1", HOJE)
    assert erro.value.code == "entry_pending"


def test_quem_nao_deve_nada_continua_podendo_ficar_disponivel(session, positions, w):
    corrida_em_dinheiro_terminada(session, positions, w)
    w.riders.go_offline(session, "r1")
    w.riders.go_online(session, "r1", HOJE)
    assert online(session) is True
