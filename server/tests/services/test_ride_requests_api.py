import pytest
from sqlalchemy import func, select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow, RideRow
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger


@pytest.fixture()
def quotes():
    return QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())


@pytest.fixture()
def requests():
    return RideRequestService(None, EventCollector())


def cotar(quotes, session, now=1000.0):
    return quotes.create_quote(session, "p1", ORIGIN, pt(1500, 0), "Rua A", "Feira livre", now)


def test_a_corrida_herda_a_rota_do_preco_mostrado(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    ride = requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1010.0)
    assert repo.get_ride_details(session, ride.ride_id).route == quote.route


def test_se_a_conferencia_falhar_o_indice_do_banco_ainda_impede_a_segunda_corrida(
    quotes, requests, session, monkeypatch
):
    add_passenger(session)
    primeira, segunda = cotar(quotes, session), cotar(quotes, session)
    requests.request_ride(session, "p1", primeira.quote_id, PaymentMethod.CASH, now=1010.0)
    monkeypatch.setattr("app.services.ride_requests.passenger_block_reason", lambda session, passenger_id: None)
    with pytest.raises(NotAllowed, match="já tem uma corrida"):
        requests.request_ride(session, "p1", segunda.quote_id, PaymentMethod.CASH, now=1011.0)
    assert session.execute(select(func.count()).select_from(RideRow)).scalar_one() == 1
    assert session.get(QuoteRow, segunda.quote_id).used is False       # a cotação não foi gasta
