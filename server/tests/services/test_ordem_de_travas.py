"""Ordem das travas do banco: corrida, corrida da fila, motoqueiro (evita impasse entre transações).

Revisão final do plano 2B: terminar uma corrida travava o motoqueiro e só depois a corrida da fila,
enquanto o Pix ou o cancelamento da corrida da fila travavam a fila e depois o motoqueiro.
"""
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.domain.dispatch import ReservationBook
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.sweeps import SweepService
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride
from tests.services.test_trips import AGORA, _com_corrida_na_fila, aceitar


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def w(positions):
    provider, events = FakePaymentProvider(), EventCollector()
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    trips = TripService(payments, dispatch, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, trips=trips, provider=provider,
        sweeps=SweepService(payments, dispatch, trips, events),
    )


@pytest.fixture()
def travas(db_engine):
    """Lista, na ordem, das travas (`FOR UPDATE`) pedidas ao banco: (tabela, valores dos parâmetros)."""
    registro: list[tuple[str, tuple]] = []

    def antes(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            tabela = re.search(r"FROM (\w+)", statement).group(1)
            valores = tuple(parameters.values()) if isinstance(parameters, dict) else tuple(parameters or ())
            registro.append((tabela, valores))

    event.listen(db_engine, "before_cursor_execute", antes)
    yield registro
    event.remove(db_engine, "before_cursor_execute", antes)


def posicao(registro, tabela, valor=None):
    for i, (t, valores) in enumerate(registro):
        if t == tabela and (valor is None or valor in valores):
            return i
    raise AssertionError(f"nenhuma trava em {tabela} {valor}: {registro}")


def _fila_com_corrida_aceita(session, positions, w):
    """r1 aceitou ride-0 (ainda não começou) e aceitou ride-1 para a fila."""
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0",
            destination=pt(300, 0))
    positions.update("r1", pt(150, 0), now=AGORA + 100)
    add_searching_ride(session, "ride-1", "p1", method=PaymentMethod.CASH, now=AGORA + 100)
    w.dispatch.offer_next(session, "ride-1", AGORA + 100)
    w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101)


def test_terminar_corrida_trava_a_da_fila_antes_do_motoqueiro(w, session, positions, travas):
    _com_corrida_na_fila(session, positions, w)
    travas.clear()
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    assert posicao(travas, "rides", "ride-0") < posicao(travas, "rides", "ride-1") < posicao(travas, "rider_profiles")


def test_cancelar_corrida_trava_a_da_fila_antes_do_motoqueiro(w, session, positions, travas):
    _fila_com_corrida_aceita(session, positions, w)
    travas.clear()
    w.trips.cancel_by_passenger(session, "p0", "ride-0", AGORA + 200)
    assert posicao(travas, "rides", "ride-0") < posicao(travas, "rides", "ride-1") < posicao(travas, "rider_profiles")


def test_varredura_da_espera_na_chegada_trava_a_corrida_a_da_fila_e_o_motoqueiro_nessa_ordem(
    w, session, positions, travas
):
    _fila_com_corrida_aceita(session, positions, w)
    w.trips.arrive(session, "r1", "ride-0", AGORA + 150)
    travas.clear()
    assert w.sweeps.run(session, AGORA + 150 + 300).arrival_cancelled == 1
    assert posicao(travas, "rides", "ride-0") < posicao(travas, "rides", "ride-1") < posicao(travas, "rider_profiles")
