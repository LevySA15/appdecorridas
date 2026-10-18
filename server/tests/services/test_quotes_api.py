import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db.models import QuoteRow
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.quotes import NotAllowed, QuoteService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_accepted_ride, add_passenger, make_online_rider


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def service(positions):
    return QuoteService(FakeMaps(), positions, InMemoryFactorStore())


def cotar(service, session, destino=pt(1500, 0), now=1000.0):
    return service.create_quote(session, "p1", ORIGIN, destino, "Rua A", "Feira livre", now)


def test_cotacao_guarda_a_rota_do_mapa_para_o_aviso_de_saida_da_rota(service, session):
    add_passenger(session)
    quote = cotar(service, session)
    assert quote.route == ((ORIGIN.lat, ORIGIN.lng), (pt(1500, 0).lat, pt(1500, 0).lng))
    assert session.execute(select(QuoteRow.route)).scalar_one() == [list(p) for p in quote.route]


@pytest.mark.parametrize("destino, trecho", [(ORIGIN, "perto"), (pt(30, 0), "perto"), (pt(50_000, 0), "longe")])
def test_trajeto_curto_demais_ou_longo_demais_e_recusado(service, session, destino, trecho):
    add_passenger(session)
    with pytest.raises(NotAllowed, match=trecho):
        cotar(service, session, destino)
    assert session.execute(select(QuoteRow)).first() is None


def test_tempo_de_chegada_estimado_vem_da_moto_livre_mais_proxima(service, session, positions):
    add_passenger(session)
    sem_motos = cotar(service, session)
    assert sem_motos.eta_seconds is None and sem_motos.nearby_riders == 0
    make_online_rider(session, positions, 1, pt(700, 0), now=1000.0)
    make_online_rider(session, positions, 2, pt(300, 0), now=1000.0)
    com_motos = cotar(service, session)
    assert com_motos.nearby_riders == 2
    assert com_motos.eta_seconds == pytest.approx(300 * 1.3 / 7.0, abs=3)      # a mais perto, em linha reta x 1,3 a 25 km/h


def test_moto_ocupada_nao_entra_na_estimativa(service, session, positions):
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000010")
    ocupada = make_online_rider(session, positions, 1, pt(100, 0), now=1000.0)
    livre = make_online_rider(session, positions, 2, pt(900, 0), now=1000.0)
    add_accepted_ride(session, ride_id="ride-9", passenger_id="p2", rider_id=ocupada)
    quote = cotar(service, session)
    assert quote.nearby_riders == 1
    assert quote.eta_seconds == pytest.approx(900 * 1.3 / 7.0, abs=3)
    assert livre
