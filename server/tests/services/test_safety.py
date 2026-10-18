import pytest
from sqlalchemy import select

from app.adapters.fake_notifier import FakeContactNotifier
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RideRow, SafetyAlertRow, UserRow
from app.domain.config import SafetyConfig
from app.domain.geo import GeoPoint
from app.domain.rides import InvalidTransition
from app.infra.redis_store import InMemoryPositionStore
from app.infra.safety_store import InMemorySafetyStore
from app.services.events import EventCollector
from app.services.safety import AlertClosed, SafetyService
from app.services.trips import NotYourRide
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_in_progress_ride, add_passenger, add_rider

AGORA = 1_800_000_000.0
ROTA = ((ORIGIN.lat, ORIGIN.lng), (pt(1500, 0).lat, pt(1500, 0).lng))


@pytest.fixture()
def store():
    return InMemorySafetyStore()


@pytest.fixture()
def notifier():
    return FakeContactNotifier()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def safety(store, positions, notifier, events):
    return SafetyService(store, positions, notifier, events, AppConfig.defaults())


@pytest.fixture()
def mundo(session):
    add_passenger(session)
    add_rider(session)
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    repo.add_user(session, user_id="adm-2", phone="+5575999990001", name="Sócia", role="admin")
    add_in_progress_ride(session, route=ROTA)


def posicoes(safety, session, pontos, inicio=AGORA, passo=4.0):
    """Manda uma posição por vez, a cada `passo` segundos, e devolve os alertas criados."""
    criados = []
    for i, ponto in enumerate(pontos):
        alerta = safety.on_rider_position(session, "ride-1", "p1", ponto, inicio + i * passo)
        if alerta is not None:
            criados.append(alerta)
    return criados


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_moto_andando_na_rota_nao_gera_alerta(safety, session, mundo, events):
    caminho = [pt(10 * i, 0) for i in range(60)]
    assert posicoes(safety, session, caminho) == []
    assert session.execute(select(SafetyAlertRow)).first() is None and events.events == ()


def test_parada_longa_pergunta_ao_passageiro_e_avisa_os_administradores(safety, session, mundo, events):
    criados = posicoes(safety, session, [pt(500, 3)] * 50)           # 200 s no mesmo lugar
    assert len(criados) == 1
    alerta = session.execute(select(SafetyAlertRow)).scalar_one()
    assert (alerta.kind, alerta.status, alerta.ride_id, alerta.suspected_mock) == ("stopped", "open", "ride-1", False)
    assert (alerta.lat, alerta.lng) == pytest.approx((pt(500, 3).lat, pt(500, 3).lng))
    pergunta = next(e for e in events.events if e.type == "safety_check")
    assert pergunta.user_id == "p1" and pergunta.payload == {"ride_id": "ride-1", "alert_id": alerta.id, "kind": "stopped"}
    for admin in ("adm-1", "adm-2"):
        aviso = next(e for e in events.events if e.user_id == admin)
        assert aviso.type == "safety_alert" and aviso.payload["alert_id"] == alerta.id
        assert aviso.payload["kind"] == "stopped" and aviso.payload["ride_id"] == "ride-1"


def test_o_mesmo_aviso_nao_repete_dentro_do_prazo_e_volta_depois(safety, session, mundo):
    parado = [pt(500, 3)] * 200                                       # 800 s parado
    posicoes(safety, session, parado[:100])
    assert session.query(SafetyAlertRow).count() == 1                  # 400 s: um aviso só
    posicoes(safety, session, parado[100:], inicio=AGORA + 400)
    assert session.query(SafetyAlertRow).count() == 2                  # passou os 600 s do primeiro


def test_sair_da_rota_so_vale_depois_de_confirmado(safety, session, mundo):
    fora = [pt(500, 400)] * 3                                          # 400 m para o lado, longe dos 300 m
    assert len(posicoes(safety, session, fora[:2])) == 0
    assert len(posicoes(safety, session, fora[2:], inicio=AGORA + 8)) == 1
    assert session.execute(select(SafetyAlertRow.kind)).scalar_one() == "off_route"


def test_a_rota_vem_do_banco_na_primeira_posicao_e_fica_na_memoria(safety, session, mundo, store):
    assert store.get_route("ride-1") is None
    safety.on_rider_position(session, "ride-1", "p1", pt(10, 0), AGORA)
    assert store.get_route("ride-1") == [GeoPoint(*ponto) for ponto in ROTA]
    session.get(RideRow, "ride-1").route = None
    session.flush()
    safety.on_rider_position(session, "ride-1", "p1", pt(20, 0), AGORA + 4)
    assert store.get_route("ride-1") == [GeoPoint(*ponto) for ponto in ROTA]      # não leu de novo


def test_corrida_sem_rota_guardada_so_avisa_parada(safety, session, store):
    add_passenger(session)
    add_rider(session)
    add_in_progress_ride(session)                                       # sem rota
    assert safety.on_rider_position(session, "ride-1", "p1", pt(9000, 9000), AGORA) is None
    assert store.get_route("ride-1") == []
    longe = [pt(9000 + 100 * i, 9000) for i in range(5)]
    assert posicoes(safety, session, longe, inicio=AGORA + 4) == []


def test_localizacao_falsa_suspeita_vira_registro_da_corrida_e_aviso_uma_vez_so(safety, session, mundo, events):
    pulos = [pt(0, 0), pt(80_000, 0), pt(10, 0), pt(80_000, 0), pt(20, 0), pt(30, 0)]
    posicoes(safety, session, pulos)
    posicoes(safety, session, [pt(40, 0), pt(50, 0)], inicio=AGORA + 100)          # continua suspeito
    assert [kind for kind, _ in repo.ride_events(session, "ride-1")].count("mock_location_suspected") == 1
    assert sum(1 for e in events.events if e.type == "mock_location_suspected") == 2    # um para cada administrador


def test_passageiro_responde_que_esta_tudo_bem(safety, session, mundo, events):
    alerta = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    safety.answer_ok(session, "p1", "ride-1", alerta.id, AGORA + 300)
    session.expire_all()
    guardado = session.get(SafetyAlertRow, alerta.id)
    assert (guardado.status, guardado.answered_at) == ("ok", AGORA + 300)
    assert "safety_ok" in tipos(events, "adm-1")
    with pytest.raises(AlertClosed):
        safety.answer_ok(session, "p1", "ride-1", alerta.id, AGORA + 301)


def test_so_o_passageiro_da_corrida_responde_e_o_aviso_tem_que_ser_dela(safety, session, mundo):
    alerta = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    add_passenger(session, "p2", "+5575900000010")
    with pytest.raises(NotYourRide):
        safety.answer_ok(session, "p2", "ride-1", alerta.id, AGORA + 300)
    with pytest.raises(LookupError):
        safety.answer_ok(session, "p1", "ride-1", 999_999, AGORA + 300)
    with pytest.raises(LookupError):
        safety.answer_ok(session, "p1", "ride-outra", alerta.id, AGORA + 300)


# --- SOS ------------------------------------------------------------------------------------------


def com_contato(session):
    repo.set_emergency_contact(session, "p1", "Maria", "+5575988887777")


def test_sos_avisa_o_contato_os_administradores_e_o_proprio_passageiro(safety, session, mundo, positions, notifier, events):
    com_contato(session)
    positions.update("r1", pt(700, 20), AGORA)
    resultado = safety.sos(session, "p1", "ride-1", AGORA + 10)
    assert resultado.contact_registered is True and resultado.contact_notified is True and resultado.repeated is False
    alerta = session.execute(select(SafetyAlertRow)).scalar_one()
    assert (alerta.kind, alerta.status) == ("sos", "sos") and alerta.id == resultado.alert_id
    assert (alerta.lat, alerta.lng) == pytest.approx((pt(700, 20).lat, pt(700, 20).lng))
    [(telefone, texto)] = notifier.sent
    assert telefone == "+5575988887777" and "Passageiro p1" in texto and "AAA1A11" in texto
    assert f"https://maps.google.com/?q={pt(700, 20).lat:.6f},{pt(700, 20).lng:.6f}" in texto
    assert tipos(events, "adm-1") == ["sos"] and tipos(events, "adm-2") == ["sos"]
    enviado = next(e for e in events.events if e.type == "sos_sent")
    assert enviado.user_id == "p1" and enviado.payload["contact_notified"] is True


def test_sos_sem_contato_cadastrado_continua_valendo(safety, session, mundo, notifier):
    resultado = safety.sos(session, "p1", "ride-1", AGORA)
    assert (resultado.contact_registered, resultado.contact_notified) == (False, False)
    assert notifier.sent == [] and session.query(SafetyAlertRow).count() == 1


def test_falha_ao_avisar_o_contato_nao_impede_o_sos(safety, session, mundo, notifier):
    com_contato(session)
    notifier.fail = True
    resultado = safety.sos(session, "p1", "ride-1", AGORA)
    assert (resultado.contact_registered, resultado.contact_notified) == (True, False)
    assert session.execute(select(SafetyAlertRow.note)).scalar_one() == "falha ao avisar o contato"


def test_sos_apertado_de_novo_nao_avisa_o_contato_outra_vez(safety, session, mundo, notifier):
    com_contato(session)
    primeiro = safety.sos(session, "p1", "ride-1", AGORA)
    segundo = safety.sos(session, "p1", "ride-1", AGORA + 30)
    assert segundo.repeated is True and segundo.alert_id == primeiro.alert_id
    assert len(notifier.sent) == 1 and session.query(SafetyAlertRow).count() == 1
    terceiro = safety.sos(session, "p1", "ride-1", AGORA + 400)           # passou o prazo: avisa de novo
    assert terceiro.repeated is False and len(notifier.sent) == 2


def test_sos_leva_junto_o_aviso_aberto_da_corrida(safety, session, mundo):
    aberto = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    resultado = safety.sos(session, "p1", "ride-1", AGORA + 300)
    session.expire_all()
    assert session.get(SafetyAlertRow, aberto.id).status == "sos"
    assert resultado.alert_id != aberto.id


def test_sos_so_durante_a_corrida_e_so_do_proprio_passageiro(safety, session, mundo):
    add_passenger(session, "p2", "+5575900000010")
    with pytest.raises(NotYourRide):
        safety.sos(session, "p2", "ride-1", AGORA)
    with pytest.raises(LookupError):
        safety.sos(session, "p1", "ride-x", AGORA)
    ride = repo.get_ride(session, "ride-1", for_update=True)
    ride.state = type(ride.state).COMPLETED
    repo.save_ride(session, ride)
    with pytest.raises(InvalidTransition):
        safety.sos(session, "p1", "ride-1", AGORA)


# --- administrador ----------------------------------------------------------------------------------


def test_administrador_encerra_o_alerta_com_uma_anotacao(safety, session, mundo):
    alerta = safety.sos(session, "p1", "ride-1", AGORA)
    safety.resolve(session, alerta.alert_id, "adm-1", "Liguei, estava tudo certo.", AGORA + 600)
    session.expire_all()
    guardado = session.get(SafetyAlertRow, alerta.alert_id)
    assert (guardado.status, guardado.resolved_by, guardado.resolved_at, guardado.note) == (
        "resolved", "adm-1", AGORA + 600, "Liguei, estava tudo certo.",
    )
    with pytest.raises(AlertClosed):
        safety.resolve(session, alerta.alert_id, "adm-2", "", AGORA + 700)
    with pytest.raises(LookupError):
        safety.resolve(session, 999_999, "adm-1", "", AGORA)


def test_limites_vem_da_configuracao(session, mundo, store, positions, notifier, events):
    cfg = AppConfig.defaults()
    cfg = AppConfig(cfg.pricing, cfg.fees, cfg.rides, cfg.dispatch, SafetyConfig(stopped_after_s=30, alert_cooldown_s=60))
    rapido = SafetyService(store, positions, notifier, events, cfg)
    assert len(posicoes(rapido, session, [pt(500, 3)] * 12)) == 1          # 44 s já basta
    assert session.get(UserRow, "p1") is not None
