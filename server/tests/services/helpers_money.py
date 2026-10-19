"""Montagem comum dos testes de saldo, taxa de cancelamento e recurso."""
import dataclasses
from types import SimpleNamespace

from app.adapters.fake_maps import FakeMaps
from app.db.config_store import AppConfig
from app.domain.config import BalanceConfig
from app.domain.dispatch import ReservationBook
from app.domain.types import PaymentMethod
from app.services.dispatch import DispatchService
from app.services.passenger_money import PassengerMoneyService
from app.services.payments import PaymentService
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, make_online_rider
from tests.services.test_trips import AGORA, aceitar, pagar

FORA_DA_JANELA = AGORA + 4 + 301            # 300 s de janela grátis, contados do aceite (AGORA + 4)
LIGADA = dataclasses.replace(
    AppConfig.defaults(), balance=BalanceConfig(topup_enabled=True, topup_min_cents=100, topup_max_cents=20_000)
)


def make_world(positions, provider, events) -> SimpleNamespace:
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, provider=provider,
        trips=TripService(payments, dispatch, events, positions=positions),
        money=PassengerMoneyService(payments, events, LIGADA),
        desligado=PassengerMoneyService(payments, events),
    )


def com_pendencia(session, positions, w, balance_cents=0):
    """Passageiro cancela tarde uma corrida em dinheiro (moto parada a 2000 m): taxa de R$ 3,00."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    if balance_cents:
        recarregar(session, w, balance_cents)
    return w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)


def pix_pago_e_cancelado(session, positions, w, balance_cents=0):
    """Pix de R$ 7,00 pago, moto com 900 m andados de 2000 (taxa de R$ 4,00), cancelado fora da janela."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    aceitar(session, positions, w)
    pagar(session, w)
    positions.update("r1", pt(1100, 0), AGORA + 300)
    if balance_cents:
        recarregar(session, w, balance_cents)
    return w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)


def recarregar(session, w, cents):
    """Põe saldo de verdade (pela recarga e pelo aviso do Pix), para o livro-caixa também enxergar."""
    charge = w.money.topup(session, "p1", cents, AGORA)
    assert w.payments.on_provider_event(session, w.provider.mark_paid(charge.charge_id)) == "applied"


def avisos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]
