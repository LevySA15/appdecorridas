import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow
from app.domain.rides import PassengerAccount, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteExpired, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger


class DespachanteFalso:
    def __init__(self):
        self.chamadas = []

    def offer_next(self, session, ride_id, now):
        self.chamadas.append((ride_id, now))
        return None


@pytest.fixture()
def quotes():
    return QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())


@pytest.fixture()
def despachante():
    return DespachanteFalso()


@pytest.fixture()
def requests(despachante):
    return RideRequestService(despachante, EventCollector())


def cotar(quotes, session, now=1000.0, passenger="p1"):
    return quotes.create_quote(session, passenger, ORIGIN, pt(1500, 0), "Rua A", "Feira livre", now)


def test_pedido_cria_corrida_em_procura_com_o_preco_travado(quotes, requests, despachante, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    ride = requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    assert ride.state is RideState.SEARCHING and ride.searching_since == 1010.0
    assert ride.price_cents == quote.price_cents == 600
    assert len(ride.pin) == 4 and ride.pin.isdigit()
    detalhes = repo.get_ride_details(session, ride.ride_id)
    assert (detalhes.pickup_text, detalhes.destination_text) == ("Rua A", "Feira livre")
    assert abs(detalhes.pickup.lat - ORIGIN.lat) < 1e-9 and detalhes.price_factor == 1.0
    assert session.execute(select(QuoteRow.used)).scalar_one() is True
    assert [kind for kind, _ in repo.ride_events(session, ride.ride_id)] == ["requested"]
    assert despachante.chamadas == [(ride.ride_id, 1010.0)]
    assert repo.get_ride(session, ride.ride_id) == ride


def test_o_mesmo_preco_nao_serve_duas_vezes(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1010.0)
    with pytest.raises(QuoteExpired, match="Peça de novo"):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1011.0)


def test_preco_vencido_ou_inexistente_ou_de_outra_pessoa_nao_vale(quotes, requests, session):
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000012")
    quote = cotar(quotes, session)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1000.0 + 301)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p2", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p1", "q-nao-existe", PaymentMethod.PIX, now=1010.0)
    assert session.execute(select(QuoteRow.used)).scalar_one() is False


def test_passageiro_com_pagamento_pendente_nao_pede(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    with pytest.raises(NotAllowed, match="Falta pagar"):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    assert session.execute(select(QuoteRow.used)).scalar_one() is False


def test_nao_da_para_ter_duas_corridas_abertas(quotes, requests, session):
    add_passenger(session)
    primeira = cotar(quotes, session)
    requests.request_ride(session, "p1", primeira.quote_id, PaymentMethod.PIX, now=1010.0)
    with pytest.raises(NotAllowed, match="já tem uma corrida"):
        cotar(quotes, session, now=1020.0)
