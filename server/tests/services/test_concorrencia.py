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
from app.db.models import RideRow
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger


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
