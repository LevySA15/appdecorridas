import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow, RiderProfileRow, UserRow
from app.domain.rides import PassengerAccount
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.quotes import NotAllowed, QuoteService, passenger_block_reason
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider, add_searching_ride, make_online_rider

DESTINO = pt(1500, 0)  # em linha reta 1.500 m; no mapa falso vira 1.950 m (x 1,3)


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def factors():
    return InMemoryFactorStore()


@pytest.fixture()
def service(positions, factors):
    return QuoteService(FakeMaps(), positions, factors)


def cotar(service, session, now=1000.0, passenger="p1"):
    return service.create_quote(session, passenger, ORIGIN, DESTINO, "Rua A", "Feira livre", now)


def test_cotacao_normal_sem_demanda_e_sem_motos(service, session, factors):
    add_passenger(session)
    quote = cotar(service, session)
    assert quote.quote_id.startswith("q-")
    assert abs(quote.distance_m - 1950) <= 5
    assert quote.price_cents == 600 and quote.factor == 1.0
    assert quote.reason == "Preço normal para este horário."
    assert quote.expires_at == 1300.0
    row = session.execute(select(QuoteRow)).scalar_one()
    assert (row.id, row.passenger_id, row.price_cents, row.used) == (quote.quote_id, "p1", 600, False)
    assert factors.get() == 1.0


def test_muito_pedido_e_pouca_moto_sobe_o_preco_aos_poucos(service, session, factors):
    add_passenger(session)
    for i in (2, 3, 4):
        add_passenger(session, f"p{i}", f"+5575900001{i:03d}")
        add_searching_ride(session, f"ride-{i}", f"p{i}")
    primeira = cotar(service, session, now=1000.0)
    assert primeira.factor == pytest.approx(1.1) and primeira.price_cents == 650
    segunda = cotar(service, session, now=1010.0)
    assert segunda.factor == pytest.approx(1.2) and segunda.price_cents == 700
    assert segunda.reason == "Poucas motos agora, preço maior."


def test_muita_moto_livre_baixa_o_preco(service, session, positions):
    add_passenger(session)
    for n in range(1, 5):
        make_online_rider(session, positions, n, pt(300 * n, 0), now=100.0)
    quote = cotar(service, session, now=110.0)
    assert quote.factor == pytest.approx(0.9) and quote.price_cents == 550
    assert quote.reason == "Muita moto livre agora, preço menor."


def test_moto_offline_velha_ou_ocupada_nao_conta_como_livre(service, session, positions):
    add_passenger(session)
    add_passenger(session, "p9", "+5575900001999")
    off = make_online_rider(session, positions, 1, pt(300, 0), now=100.0)
    session.get(RiderProfileRow, off).online = False
    make_online_rider(session, positions, 2, pt(400, 0), now=10.0)         # posição de 100 s atrás
    ocupada = make_online_rider(session, positions, 3, pt(500, 0), now=100.0)
    add_accepted_ride(session, ride_id="ride-9", passenger_id="p9", rider_id=ocupada)
    session.flush()
    quote = cotar(service, session, now=110.0)
    assert quote.factor == 1.0 and quote.price_cents == 600


def test_passageiro_com_restricao_nao_recebe_preco(service, session):
    add_passenger(session)
    session.get(UserRow, "p1").is_blocked = True
    session.flush()
    with pytest.raises(NotAllowed, match="bloqueada"):
        cotar(service, session)
    assert session.execute(select(QuoteRow)).first() is None


def test_motivos_para_nao_poder_pedir(session):
    add_passenger(session)
    add_rider(session)
    assert passenger_block_reason(session, "p1") is None
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=0))
    add_searching_ride(session, "ride-1", "p1")
    assert "já tem uma corrida" in passenger_block_reason(session, "p1")


def test_corrida_em_dinheiro_concluida_e_nao_paga_impede_novo_pedido(session):
    from app.domain.rides import RideState
    from app.domain.types import PaymentMethod

    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session, method=PaymentMethod.CASH)
    ride.state = RideState.COMPLETED
    repo.save_ride(session, ride)
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    ride.end_payment_confirmed = True
    repo.save_ride(session, ride)
    assert passenger_block_reason(session, "p1") is None
