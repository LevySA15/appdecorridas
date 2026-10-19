"""Devolução que não chega à chave Pix do passageiro vira saldo dele no app (decisão do Levy, 19/10/2026)."""
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.payments import PaymentService
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider

FEE = 100


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def service(provider, events):
    return PaymentService(provider, events=events)


def mundo(session, debt=1000, busy=False):
    add_passenger(session)
    add_rider(session, debt_cents=debt)
    return add_accepted_ride(session, busy=busy, method=PaymentMethod.PIX)


def pagar(session, service, provider):
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    return charge


def saldo(session) -> int:
    return repo.get_passenger_account(session, "p1").balance_cents


def test_devolucao_que_nao_chega_vira_saldo(session, service, provider):
    mundo(session)
    charge = pagar(session, service, provider)
    provider.refund_all_undeliverable = True
    resultado = service.cancel_ride(session, "ride-1", now=20)
    assert resultado.refund_needed is True
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert saldo(session) == 700
    ledger = PgLedger(session)
    assert ledger.balance("balance:p1") == 700
    assert ledger.balance("rider:r1") == 0 and ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == -700            # o dinheiro continua com o provedor
    assert ledger.is_balanced() is True
    assert repo.get_charge(session, charge.charge_id).refunded is True
    assert provider.charges[charge.charge_id].refunded_cents == 0
    acc = repo.get_rider_account(session, "r1")
    assert (acc.cash_debt_cents, acc.debt_reserved_cents) == (1000, 0)      # a dívida abatida voltou


def test_devolucao_normal_continua_indo_para_o_pix(session, service, provider):
    mundo(session)
    charge = pagar(session, service, provider)
    service.cancel_ride(session, "ride-1", now=20)
    assert saldo(session) == 0
    assert provider.charges[charge.charge_id].refunded_cents == 700
    assert PgLedger(session).balance("balance:p1") == 0


def test_pix_pago_atrasado_depois_do_cancelamento_tambem_cai_no_saldo(session, service, provider, events):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.cancel_ride(session, "ride-1", now=20)              # cancelou antes de o Pix chegar
    events.drain()
    provider.refund_all_undeliverable = True
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    assert saldo(session) == 700
    refunded = [e for e in events.drain() if e.type == "payment_refunded"]
    assert len(refunded) == 1 and refunded[0].user_id == "p1"
    assert refunded[0].payload["to"] == "balance" and refunded[0].payload["balance_cents"] == 700
    assert PgLedger(session).is_balanced() is True


def test_aviso_de_devolucao_normal_diz_que_foi_para_o_pix(session, service, provider, events):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.cancel_ride(session, "ride-1", now=20)
    events.drain()
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    refunded = [e for e in events.drain() if e.type == "payment_refunded"]
    assert refunded[0].payload["to"] == "pix" and "balance_cents" not in refunded[0].payload


def test_fila_desfeita_com_devolucao_que_nao_chega_vira_saldo(session, service, provider):
    mundo(session, busy=True)
    pagar(session, service, provider)
    provider.refund_all_undeliverable = True
    assert service.release_queued_ride(session, "ride-1", now=30) is True
    assert saldo(session) == 700
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
    assert PgLedger(session).is_balanced() is True


def test_saldo_acumula_duas_devolucoes_que_nao_chegaram(session, service, provider):
    mundo(session)
    pagar(session, service, provider)
    provider.refund_all_undeliverable = True
    service.cancel_ride(session, "ride-1", now=20)
    add_accepted_ride(session, ride_id="ride-2", now=40.0)
    charge2 = service.start_pix_charge(session, "ride-2", FEE)
    service.on_provider_event(session, provider.mark_paid(charge2.charge_id))
    service.cancel_ride(session, "ride-2", now=50)
    assert saldo(session) == 1400
    assert PgLedger(session).balance("balance:p1") == 1400
