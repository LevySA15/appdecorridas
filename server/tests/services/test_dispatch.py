import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.models import RideOfferRow
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore, RedisReservationBook
from app.services.dispatch import DispatchService, OfferGone
from app.services.events import EventCollector
from app.services.payments import PaymentService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import (
    add_accepted_ride,
    add_completed_rides_today,
    add_passenger,
    add_searching_ride,
    make_online_rider,
)

AGORA = 1_800_000_000.0


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def reservas():
    return ReservationBook()


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def dispatch(positions, reservas, provider, events):
    return DispatchService(positions, reservas, FakeMaps(), PaymentService(provider), events)


def tipos(events, user_id=None):
    return [e.type for e in events.events if user_id is None or e.user_id == user_id]


def mundo(session, positions, n_motos=2, method=PaymentMethod.PIX):
    add_passenger(session)
    riders = [make_online_rider(session, positions, n, pt(200 * n, 0), now=AGORA) for n in range(1, n_motos + 1)]
    add_searching_ride(session, method=method, now=AGORA)
    return riders


def test_oferta_vai_para_a_moto_mais_perto_e_avisa_o_motoqueiro(dispatch, session, positions, events):
    mundo(session, positions)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    oferta = session.query(RideOfferRow).one()
    assert (oferta.rider_id, oferta.status, oferta.will_queue) == ("r1", "pending", False)
    assert oferta.expires_at == AGORA + 15
    aviso = next(e for e in events.events if e.type == "offer")
    assert aviso.user_id == "r1" and aviso.payload["ride_id"] == "ride-1"
    assert aviso.payload["price_cents"] == 700 and aviso.payload["payment_method"] == "pix"
    assert aviso.payload["expires_at"] == AGORA + 15


def test_sem_motos_por_perto_nao_ha_oferta(dispatch, session, positions):
    add_passenger(session)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    make_online_rider(session, positions, 1, pt(9000, 0), now=AGORA)  # fora do raio de 3 km
    assert dispatch.offer_next(session, "ride-1", AGORA) is None


def test_moto_offline_bloqueada_ou_com_posicao_velha_nao_recebe(dispatch, session, positions):
    from app.db.models import RiderProfileRow, UserRow

    mundo(session, positions, n_motos=4)
    session.get(RiderProfileRow, "r1").online = False
    session.get(UserRow, "r2").is_blocked = True
    positions.update("r3", pt(600, 0), now=AGORA - 100)
    session.flush()
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r4"


def test_oferta_repetida_devolve_a_mesma_enquanto_nao_vence(dispatch, session, positions):
    mundo(session, positions)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert dispatch.offer_next(session, "ride-1", AGORA + 5) == "r1"
    assert session.query(RideOfferRow).count() == 1


def test_a_mesma_moto_nunca_recebe_dois_pedidos_ao_mesmo_tempo(dispatch, session, positions):
    # Review Focus 2
    mundo(session, positions, n_motos=1)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert dispatch.offer_next(session, "ride-2", AGORA) is None


def test_recusa_passa_para_a_proxima_e_quem_recusou_nao_recebe_de_novo(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    assert dispatch.decline_offer(session, "r1", "ride-1", AGORA + 3) == "r2"
    assert dispatch.decline_offer(session, "r2", "ride-1", AGORA + 6) is None
    assert dispatch.offer_next(session, "ride-1", AGORA + 7) is None
    estados = {o.rider_id: o.status for o in session.query(RideOfferRow)}
    assert estados == {"r1": "declined", "r2": "declined"}


def test_recusar_oferta_que_nao_e_sua_da_erro(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    with pytest.raises(OfferGone):
        dispatch.decline_offer(session, "r2", "ride-1", AGORA + 1)


def test_oferta_vencida_vira_expirada_e_a_proxima_moto_recebe(dispatch, session, positions, events):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    assert dispatch.expire_offers(session, AGORA + 14) == 0
    assert dispatch.expire_offers(session, AGORA + 16) == 1
    estados = {o.rider_id: o.status for o in session.query(RideOfferRow)}
    assert estados == {"r1": "expired", "r2": "pending"}
    assert "offer_expired" in tipos(events, "r1")


def test_aceitar_oferta_vencida_ou_de_outro_motoqueiro_ou_duas_vezes_da_erro(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r2", "ride-1", AGORA + 1)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 15)
    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 3)


def test_aceitar_corrida_pix_cria_a_cobranca_e_avisa_o_passageiro(dispatch, session, positions, events, reservas):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    assert ride.state is RideState.ACCEPTED and ride.rider_id == "r1" and ride.fee_cents == 100
    assert ride.pix_charge_created_at == AGORA + 4
    assert repo.get_current_charge_id(session, "ride-1") is not None
    assert session.query(RideOfferRow).one().status == "accepted"
    assert reservas.reserve("r1", "ride-outra") is True  # a reserva foi liberada
    aviso = next(e for e in events.events if e.type == "rider_accepted")
    assert aviso.user_id == "p1"
    assert aviso.payload["pin"] == "4821" and aviso.payload["queued"] is False
    assert aviso.payload["rider"] == {
        "rider_id": "r1", "name": "Motoqueiro r1", "plate": "ABC0001", "moto_model": "Honda CG 160",
        "rating": None, "rating_count": 0, "photo_url": None,
    }                                          # a ficha pública: sem a chave interna da foto
    assert aviso.payload["pay"]["amount_cents"] == 700 and aviso.payload["queue"] is None
    assert "ride_assigned" in tipos(events, "r1")
    assert [k for k, _ in repo.ride_events(session, "ride-1")] == ["offered", "accepted"]


def test_aceitar_corrida_em_dinheiro_nao_cria_cobranca(dispatch, session, positions, events):
    mundo(session, positions, method=PaymentMethod.CASH)
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    assert ride.state is RideState.ACCEPTED
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert next(e for e in events.events if e.type == "rider_accepted").payload["pay"] is None


def test_taxa_depende_de_quantas_corridas_o_motoqueiro_ja_fez_hoje(dispatch, session, positions):
    mundo(session, positions, n_motos=1)
    add_completed_rides_today(session, "r1", 5, AGORA)
    from app.db.models import RideRow  # corrida de dois dias atrás não conta

    session.add(RideRow(id="velha", passenger_id="p1", rider_id="r1", price_cents=700, payment_method="pix",
                        pin="4821", state="completed", completed_at=AGORA - 2 * 86400))
    session.flush()
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 1)
    assert ride.fee_cents == 90  # é a 6ª do dia: faixa de R$ 0,90


def _moto_terminando(session, positions, n=1):
    """Motoqueiro com uma corrida em andamento cujo destino está a 200 m do ponto de partida do novo pedido."""
    rider = make_online_rider(session, positions, n, pt(100, 0), now=AGORA)
    add_passenger(session, "p0", "+5575900000010")
    add_accepted_ride(session, ride_id="ride-0", passenger_id="p0", rider_id=rider)
    repo.set_ride_details(
        session, "ride-0",
        repo.RideDetails(pt(-2000, 0), pt(300, 0), "Origem", "Destino", 2300, 1.0, ""),
    )
    return rider


def test_moto_terminando_recebe_pedido_para_a_fila(dispatch, session, positions, events):
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert session.query(RideOfferRow).filter_by(ride_id="ride-1").one().will_queue is True
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    assert ride.state is RideState.QUEUED and ride.queued_since == AGORA + 2
    assert repo.get_current_charge_id(session, "ride-1") is not None  # o Pix nasce ao aceitar a da fila
    assert next(e for e in events.events if e.type == "rider_accepted").payload["queued"] is True


def test_passageiro_da_fila_sabe_onde_a_moto_termina_e_quando_chega(dispatch, session, positions, events):
    # Spec 5.2: "a moto está terminando uma corrida em [ponto] e chega em X minutos".
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, now=AGORA)
    dispatch.offer_next(session, "ride-1", AGORA)
    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    fila = next(e for e in events.events if e.type == "rider_accepted").payload["queue"]
    assert fila["finishing_at"] == "Destino" and fila["eta_seconds"] > 0


def test_moto_que_ja_tem_corrida_na_fila_nao_recebe_outra(dispatch, session, positions):
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, "ride-1", now=AGORA)
    dispatch.offer_next(session, "ride-1", AGORA)
    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 1)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    assert dispatch.offer_next(session, "ride-2", AGORA + 2) is None


def test_moto_na_10a_corrida_sem_entrada_nao_recebe_pedido_para_a_fila(dispatch, session, positions):
    # Review Focus 3 (lado da procura): a 11ª corrida não pode nascer para quem não pagou a entrada.
    add_passenger(session)
    rider = _moto_terminando(session, positions)
    acc = repo.get_rider_account(session, rider)
    acc.completed_rides = 9           # a corrida em andamento é a 10ª
    repo.save_rider_account(session, acc)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    acc.entry_paid = True
    repo.save_rider_account(session, acc)
    assert dispatch.offer_next(session, "ride-1", AGORA) == rider


def test_motoqueiro_na_10a_corrida_livre_ainda_recebe_a_10a(dispatch, session, positions):
    add_passenger(session)
    rider = make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    acc = repo.get_rider_account(session, rider)
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == rider


def test_divida_de_uma_taxa_nao_recebe_oferta_nenhuma_nem_em_dinheiro_nem_em_pix(dispatch, session, positions):
    add_passenger(session)
    rider = make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    acc = repo.get_rider_account(session, rider)
    acc.cash_debt_cents = 100
    repo.save_rider_account(session, acc)
    add_searching_ride(session, "ride-1", method=PaymentMethod.CASH, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", method=PaymentMethod.PIX, now=AGORA)
    assert dispatch.offer_next(session, "ride-2", AGORA) is None
    acc.cash_debt_cents = 69                                   # pagou quase tudo: abaixo do limite volta a receber
    repo.save_rider_account(session, acc)
    assert dispatch.offer_next(session, "ride-2", AGORA) == rider


def test_com_reserva_no_redis_a_moto_tambem_nao_recebe_dois_pedidos(session, positions, provider, events, redis_client):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-1", now=AGORA)
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    servico = DispatchService(
        positions, RedisReservationBook(redis_client, ttl_ms=20_000), FakeMaps(), PaymentService(provider), events
    )
    assert servico.offer_next(session, "ride-1", AGORA) == "r1"
    assert servico.offer_next(session, "ride-2", AGORA) is None
    servico.decline_offer(session, "r1", "ride-1", AGORA + 1)
    assert servico.offer_next(session, "ride-2", AGORA + 2) == "r1"


def test_so_oferece_corrida_que_ainda_esta_em_procura(dispatch, session, positions):
    mundo(session, positions)
    ride = repo.get_ride(session, "ride-1")
    ride.state = RideState.CANCELLED
    repo.save_ride(session, ride)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None


class MapaContador(FakeMaps):
    """Mapa falso que conta quantas vezes o tempo de rota foi pedido (cada pedido custa dinheiro no Google)."""

    def __init__(self):
        super().__init__()
        self.chamadas = 0

    def eta_seconds(self, origin, destination):
        self.chamadas += 1
        return super().eta_seconds(origin, destination)


@pytest.fixture()
def mapa():
    return MapaContador()


@pytest.fixture()
def dispatch_contando(positions, reservas, provider, events, mapa):
    return DispatchService(positions, reservas, mapa, PaymentService(provider), events)


def test_nao_calcula_rota_para_moto_ocupada_que_esta_longe_de_terminar(dispatch_contando, session, positions, mapa):
    # Revisão final do plano 2B (I5): a rota só vale a pena para quem pode estar terminando.
    add_passenger(session)
    _moto_terminando(session, positions)
    repo.set_ride_details(session, "ride-0", repo.RideDetails(pt(-2000, 0), pt(5000, 0), "A", "B", 7000, 1.0, ""))
    add_searching_ride(session, now=AGORA)
    mapa.chamadas = 0
    assert dispatch_contando.offer_next(session, "ride-1", AGORA) is None
    assert mapa.chamadas == 0


def test_nao_calcula_rota_para_moto_que_ja_recusou_o_pedido(dispatch_contando, session, positions, mapa):
    add_passenger(session)
    rider = _moto_terminando(session, positions)
    add_searching_ride(session, now=AGORA)
    session.add(RideOfferRow(ride_id="ride-1", rider_id=rider, status="declined", will_queue=True,
                             created_at=AGORA - 5, expires_at=AGORA + 10))
    session.flush()
    mapa.chamadas = 0
    assert dispatch_contando.offer_next(session, "ride-1", AGORA) is None
    assert mapa.chamadas == 0


def test_nao_calcula_rota_para_moto_que_ja_tem_corrida_na_fila(dispatch_contando, session, positions, mapa):
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, "ride-1", now=AGORA)
    dispatch_contando.offer_next(session, "ride-1", AGORA)
    dispatch_contando.accept_offer(session, "r1", "ride-1", AGORA + 1)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    mapa.chamadas = 0
    assert dispatch_contando.offer_next(session, "ride-2", AGORA + 2) is None
    assert mapa.chamadas == 0


def test_ainda_calcula_a_rota_da_moto_que_esta_terminando_perto(dispatch_contando, session, positions, mapa):
    add_passenger(session)
    rider = _moto_terminando(session, positions)
    add_searching_ride(session, now=AGORA)
    mapa.chamadas = 0
    assert dispatch_contando.offer_next(session, "ride-1", AGORA) == rider
    assert mapa.chamadas >= 1


def test_oferta_guarda_o_tempo_ate_o_passageiro_para_o_app_mostrar_ao_reconectar(dispatch, session, positions, events):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    aviso = next(e for e in events.events if e.type == "offer")
    assert session.query(RideOfferRow).one().eta_seconds == aviso.payload["seconds_to_pickup"] > 0


def test_motoqueiro_que_ficou_indisponivel_depois_da_oferta_nao_consegue_aceitar(dispatch, session, positions):
    # Roteiro do 2B (menores): `accept_offer` não reconferia o bloqueio.
    from app.db.models import RiderProfileRow, UserRow

    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    session.get(RiderProfileRow, "r1").online = False
    session.flush()
    with pytest.raises(OfferGone, match="disponível"):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    session.get(RiderProfileRow, "r1").online = True
    session.get(UserRow, "r1").is_blocked = True
    session.flush()
    with pytest.raises(OfferGone, match="disponível"):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 3)
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING


def test_ficha_publica_aponta_para_a_selfie_quando_ela_existe(session, positions):
    from app.db import queries
    from app.db.models import RiderProfileRow

    mundo(session, positions, n_motos=1)
    assert queries.rider_card(session, "r1").public()["photo_url"] is None
    session.get(RiderProfileRow, "r1").selfie_key = "r1/selfie-0123456789abcdef.jpg"
    session.flush()
    ficha = queries.rider_card(session, "r1").public()
    assert ficha["photo_url"] == "/v1/riders/r1/documents/selfie" and "selfie_key" not in ficha
