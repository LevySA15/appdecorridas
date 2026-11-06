"""Testes com duas conexões reais ao banco (cada uma com seu commit).

Os dados ficam gravados de verdade no esquema temporário; a limpeza no fim apaga tudo, menos o
livro-caixa (que o banco não deixa apagar e que estes testes não tocam).
"""
import threading
import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_notifier import FakeContactNotifier
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RideRow, SafetyAlertRow
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.infra.safety_store import InMemorySafetyStore
from app.services.events import EventCollector
from app.services.safety import SafetyService
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_in_progress_ride, add_passenger, add_rider


@pytest.fixture()
def sessoes_reais(db_engine):
    fabrica = sessionmaker(db_engine, expire_on_commit=False)
    yield fabrica
    with db_engine.begin() as conn:
        for tabela in (
            "ride_events", "ride_offers", "ratings", "pix_charges", "rides", "quotes", "sessions",
            "passenger_profiles", "rider_profiles", "otp_codes", "users",
        ):
            conn.execute(text(f"DELETE FROM {tabela}"))


def test_dois_pedidos_ao_mesmo_tempo_do_mesmo_passageiro_so_um_vira_corrida(sessoes_reais):
    # Revisão final do plano 2B (I2): só a cotação era travada, então duas cotações passavam juntas.
    cotacoes = {}
    with sessoes_reais() as s:
        add_passenger(s)
        quotes = QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())
        for nome in ("q1", "q2"):
            cotacoes[nome] = quotes.create_quote(s, "p1", ORIGIN, pt(1500, 0), "A", "B", 1000.0).quote_id
        s.commit()
    servico = RideRequestService(None, EventCollector())
    a_criou, a_pode_confirmar = threading.Event(), threading.Event()
    resultado: dict[str, str] = {}

    def pedido_a():
        with sessoes_reais() as s:
            servico.request_ride(s, "p1", cotacoes["q1"], PaymentMethod.CASH, 1010.0)
            a_criou.set()                      # criou a corrida, mas ainda não deu commit
            a_pode_confirmar.wait(5)
            s.commit()
            resultado["a"] = "ok"

    def pedido_b():
        with sessoes_reais() as s:
            try:
                servico.request_ride(s, "p1", cotacoes["q2"], PaymentMethod.CASH, 1011.0)
                s.commit()
                resultado["b"] = "ok"
            except NotAllowed:
                s.rollback()
                resultado["b"] = "recusado"

    ta = threading.Thread(target=pedido_a)
    ta.start()
    assert a_criou.wait(5)
    tb = threading.Thread(target=pedido_b)
    tb.start()
    time.sleep(0.5)                            # com a trava, B espera aqui o commit de A
    a_pode_confirmar.set()
    ta.join(10)
    tb.join(10)
    assert resultado == {"a": "ok", "b": "recusado"}
    with sessoes_reais() as s:
        assert s.execute(select(func.count()).select_from(RideRow)).scalar_one() == 1


@pytest.mark.parametrize("quem", ["passageiro", "motoqueiro"])
def test_dois_sos_ao_mesmo_tempo_criam_um_alerta_so(sessoes_reais, quem):
    # Revisão final do plano 2C: o segundo toque não achava o alerta do primeiro (ainda sem commit) e criava outro.
    agora = 1_800_000_000.0
    with sessoes_reais() as s:
        add_passenger(s)
        add_rider(s)
        repo.add_user(s, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
        add_in_progress_ride(s)
        s.commit()
    servico = SafetyService(InMemorySafetyStore(), InMemoryPositionStore(), FakeContactNotifier(), EventCollector(), AppConfig.defaults())
    if quem == "passageiro":
        pedir = lambda s: servico.sos(s, "p1", "ride-1", agora)          # noqa: E731
    else:
        pedir = lambda s: servico.rider_sos(s, "r1", "ride-1", agora)    # noqa: E731
    a_pediu, a_pode_confirmar = threading.Event(), threading.Event()
    alertas: dict[str, int] = {}

    def toque_a():
        with sessoes_reais() as s:
            alertas["a"] = pedir(s).alert_id
            a_pediu.set()                      # criou o alerta, mas ainda não deu commit
            a_pode_confirmar.wait(5)
            s.commit()

    def toque_b():
        with sessoes_reais() as s:
            alertas["b"] = pedir(s).alert_id
            s.commit()

    ta = threading.Thread(target=toque_a)
    ta.start()
    assert a_pediu.wait(5)
    tb = threading.Thread(target=toque_b)
    tb.start()
    time.sleep(0.5)                            # com a trava da corrida, B espera aqui o commit de A
    a_pode_confirmar.set()
    ta.join(10)
    tb.join(10)
    try:
        assert alertas["a"] == alertas["b"]
        with sessoes_reais() as s:
            assert s.execute(select(func.count()).select_from(SafetyAlertRow).where(SafetyAlertRow.kind == "sos")).scalar_one() == 1
    finally:
        with sessoes_reais() as s:
            s.execute(text("DELETE FROM safety_alerts"))      # as demais tabelas, a fixture limpa
            s.commit()
