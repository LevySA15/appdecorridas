"""Pedir e pagar a corrida com o saldo do passageiro."""
import dataclasses

import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow
from app.db.pg_ledger import PgLedger
from app.domain.config import BalanceConfig
from app.domain.dispatch import ReservationBook
from app.domain.rides import PassengerAccount, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from app.services.trips import TripService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger, make_online_rider
from tests.services.helpers_money import make_world, recarregar
from tests.services.test_trips import AGORA, aceitar, ate_o_fim


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
    return make_world(positions, provider, events)


def eventos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]


def saldo(session, cents):
    acc = repo.get_passenger_account(session, "p1")
    repo.save_passenger_account(session, PassengerAccount("p1", acc.unpaid_cents, cents))


# --- o pedido -----------------------------------------------------------------------------------


def _pedido(session, balance_cents, config=None, method=PaymentMethod.PIX, **extra):
    quotes = QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())
    requests = RideRequestService(None, EventCollector(), config)
    add_passenger(session)
    saldo(session, balance_cents)
    quote = quotes.create_quote(session, "p1", ORIGIN, pt(1500, 0), "Rua A", "Feira livre", 1000.0)
    return quote, lambda: requests.request_ride(session, "p1", quote.quote_id, method, now=1010.0, **extra)


def test_pedido_com_saldo_que_cobre_grava_a_marca(session):
    quote, pedir = _pedido(session, 1000, pay_with_balance=True)
    ride = pedir()
    assert ride.pay_with_balance is True and ride.payment_method is PaymentMethod.PIX and quote.price_cents == 600
    assert repo.get_ride(session, ride.ride_id).pay_with_balance is True
    assert repo.ride_events(session, ride.ride_id)[0][1]["pay_with_balance"] is True


def test_pedido_normal_nao_leva_a_marca(session):
    _, pedir = _pedido(session, 1000)
    assert pedir().pay_with_balance is False


def test_pedido_com_o_saldo_exato_do_preco_vale(session):
    _, pedir = _pedido(session, 600, pay_with_balance=True)
    assert pedir().pay_with_balance is True


def test_pedido_com_saldo_curto_e_recusado_e_a_cotacao_continua_valendo(session):
    quote, pedir = _pedido(session, 599, pay_with_balance=True)
    with pytest.raises(NotAllowed, match="saldo"):
        pedir()
    assert session.execute(select(QuoteRow.used)).scalar_one() is False


def test_pedido_com_saldo_desligado_e_recusado(session):
    desligado = dataclasses.replace(AppConfig.defaults(), balance=BalanceConfig(pay_rides_enabled=False))
    _, pedir = _pedido(session, 1000, config=desligado, pay_with_balance=True)
    with pytest.raises(NotAllowed, match="não está disponível"):
        pedir()


def test_pedido_com_saldo_so_vale_para_corrida_paga_pelo_app(session):
    _, pedir = _pedido(session, 1000, method=PaymentMethod.CASH, pay_with_balance=True)
    with pytest.raises(NotAllowed, match="pelo app"):
        pedir()


# --- o aceite ------------------------------------------------------------------------------------


def test_aceite_paga_com_o_saldo_e_o_livro_fecha(session, positions, w, provider, events):
    add_passenger(session)
    recarregar(session, w, 1000)
    events.drain()
    ride = aceitar(session, positions, w, pay_with_balance=True)
    assert ride.pix_paid is True and ride.pay_with_balance is True
    charge = repo.get_charge(session, repo.get_current_charge_id(session, "ride-1"))
    assert (charge.source, charge.paid, charge.amount_cents) == ("balance", True, 700)
    assert provider.charges == {k: v for k, v in provider.charges.items() if v.purpose == "topup"}
    assert repo.get_passenger_account(session, "p1").balance_cents == 300
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (300, 600, 100)
    assert ledger.balance(PgLedger.PROVIDER) == -1000 and ledger.is_balanced() is True
    assert eventos(events, "p1", "balance_paid") == [{"ride_id": "ride-1", "amount_cents": 700, "balance_cents": 300}]
    assert eventos(events, "r1", "payment_received") == [{"ride_id": "ride-1", "late": False}]
    aviso = eventos(events, "p1", "rider_accepted")[0]
    assert aviso["pay"] is None and aviso["paid_with_balance"] is True


def test_aceite_com_divida_do_motoqueiro_abate_como_no_pix(session, positions, w):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 60
    repo.save_rider_account(session, acc)
    recarregar(session, w, 1000)
    aceitar(session, positions, w, pay_with_balance=True)
    acc = repo.get_rider_account(session, "r1")
    assert (acc.cash_debt_cents, acc.debt_reserved_cents) == (0, 0)
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (540, 160)
    assert ledger.is_balanced() is True


def test_saldo_exato_do_preco_zera_o_saldo(session, positions, w):
    add_passenger(session)
    recarregar(session, w, 700)
    aceitar(session, positions, w, pay_with_balance=True)
    assert repo.get_passenger_account(session, "p1").balance_cents == 0


def test_saldo_que_ficou_curto_antes_do_aceite_vira_pix_comum(session, positions, w, provider, events):
    add_passenger(session)
    recarregar(session, w, 1000)
    saldo(session, 300)                  # o passageiro gastou o resto entre o pedido e o aceite
    events.drain()
    ride = aceitar(session, positions, w, pay_with_balance=True)
    assert ride.pay_with_balance is False and ride.pix_paid is False
    charge = repo.get_charge(session, repo.get_current_charge_id(session, "ride-1"))
    assert charge.source == "pix" and charge.paid is False and charge.charge_id in provider.charges
    assert repo.get_passenger_account(session, "p1").balance_cents == 300
    assert eventos(events, "p1", "balance_short") == [{"ride_id": "ride-1", "balance_cents": 300, "price_cents": 700}]
    assert eventos(events, "p1", "rider_accepted")[0]["pay"]["charge_id"] == charge.charge_id
    assert PgLedger(session).is_balanced() is True


def test_saldo_desligado_depois_do_pedido_vira_pix_comum(session, positions, provider, events):
    payments = PaymentService(provider, events=events, balance_cfg=BalanceConfig(pay_rides_enabled=False))
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    mundo = type("W", (), {"payments": payments, "dispatch": dispatch, "provider": provider})()
    add_passenger(session)
    saldo(session, 1000)
    ride = aceitar(session, positions, mundo, pay_with_balance=True)
    assert ride.pay_with_balance is False and ride.pix_paid is False
    assert repo.get_charge(session, repo.get_current_charge_id(session, "ride-1")).source == "pix"


def test_corrida_paga_com_saldo_anda_ate_o_fim_sem_esperar_pix(session, positions, w, provider):
    add_passenger(session)
    recarregar(session, w, 1000)
    aceitar(session, positions, w, pay_with_balance=True)
    ate_o_fim(session, w)
    assert repo.get_ride(session, "ride-1").state is RideState.COMPLETED
    assert PgLedger(session).is_balanced() is True
