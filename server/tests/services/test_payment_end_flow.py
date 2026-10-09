import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import DebtState
from app.domain.rides import InvalidTransition
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import passenger_block_reason
from tests.helpers_db import add_completed_ride, add_passenger, add_rider

FEE = 100
FIM = 1000.0  # instante em que a corrida terminou


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def service(provider, events):
    return PaymentService(provider, events=events)


def mundo(session, debt=0, method=PaymentMethod.CASH):
    add_passenger(session)
    add_rider(session, debt_cents=debt)
    return add_completed_ride(session, method=method, fee=FEE, completed_at=FIM)


def divida(session):
    acc = repo.get_rider_account(session, "r1")
    return acc.cash_debt_cents, acc.debt_reserved_cents


def pendente(session):
    return repo.get_passenger_account(session, "p1").unpaid_cents


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_qr_do_fim_nasce_com_a_divisao_e_reserva_a_divida(session, service):
    mundo(session, debt=400)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert charge.purpose == "end" and charge.amount_cents == 700
    assert charge.split.debt_paid_cents == 300 and charge.split.company_cents == 400
    assert repo.get_current_charge_id(session, "ride-1") == charge.charge_id
    assert divida(session) == (400, 300)
    assert service.start_end_charge(session, "ride-1", FEE).charge_id == charge.charge_id


def test_qr_so_para_corrida_em_dinheiro_ja_concluida_e_nao_paga(session, service):
    mundo(session, method=PaymentMethod.PIX)
    with pytest.raises(InvalidTransition, match="dinheiro"):
        service.start_end_charge(session, "ride-1", FEE)


def test_pago_pelo_qr_dentro_do_prazo_divide_e_abate_a_divida(session, service, provider, events):
    # Review Focus 1
    mundo(session, debt=1000)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    assert divida(session) == (700, 0)
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (300, 400, -700)
    assert ledger.is_balanced() is True
    assert pendente(session) == 0
    assert "payment_received" in tipos(events, "r1")


def test_motoqueiro_confirma_dinheiro_a_taxa_vira_divida_e_a_reserva_solta(session, service, events):
    mundo(session, debt=400)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.confirm_cash_received(session, "ride-1", now=FIM + 30)
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    assert divida(session) == (500, 0)   # 400 antigos + R$ 1,00 desta corrida; reserva solta
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED
    assert pendente(session) == 0
    assert "payment_confirmed" in tipos(events, "p1")


def test_confirmar_dinheiro_duas_vezes_da_erro(session, service):
    mundo(session)
    service.confirm_cash_received(session, "ride-1", now=FIM + 5)
    with pytest.raises(InvalidTransition, match="já foi confirmado"):
        service.confirm_cash_received(session, "ride-1", now=FIM + 6)


def test_qr_pago_depois_de_o_motoqueiro_confirmar_dinheiro_e_devolvido(session, service, provider):
    # Review Focus 1: o passageiro pagou duas vezes (dinheiro e QR).
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.confirm_cash_received(session, "ride-1", now=FIM + 5)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (0, 0, 0)
    assert divida(session) == (100, 0)   # só a taxa do dinheiro vivo que ele recebeu


def test_prazo_vencido_bloqueia_o_passageiro_sem_cobrar_taxa_do_motoqueiro(session, service, events):
    # Review Focus 1
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 299) is False
    assert pendente(session) == 0
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 300) is True
    assert pendente(session) == 700
    assert repo.get_ride(session, "ride-1").non_payment_reported is True
    assert divida(session) == (0, 0)
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    assert tipos(events, "r1") == ["passenger_blocked"]
    pendente_aviso = next(e for e in events.events if e.type == "payment_pending")
    assert pendente_aviso.user_id == "p1" and pendente_aviso.payload["charge_id"] == charge.charge_id
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 400) is False  # só uma vez


def test_motoqueiro_nao_confirma_dinheiro_depois_do_bloqueio(session, service):
    # Review Focus 1
    mundo(session)
    service.start_end_charge(session, "ride-1", FEE)
    service.block_unpaid_cash_ride(session, "ride-1", FIM + 300)
    with pytest.raises(InvalidTransition, match="Pix"):
        service.confirm_cash_received(session, "ride-1", now=FIM + 310)


def test_pagamento_atrasado_desbloqueia_o_passageiro_e_paga_o_motoqueiro_uma_vez(session, service, provider, events):
    # Review Focus 1
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.block_unpaid_cash_ride(session, "ride-1", FIM + 300)
    evento = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, evento) == "applied"
    assert pendente(session) == 0
    assert passenger_block_reason(session, "p1") is None
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (600, 100, -700)
    assert divida(session) == (0, 0)
    assert "unblocked" in tipos(events, "p1") and "payment_received" in tipos(events, "r1")
    assert service.on_provider_event(session, evento) == "duplicate"
    assert ledger.balance("rider:r1") == 600


def test_entrada_de_50_reais_cria_cobranca_sem_corrida_e_paga_uma_vez(session, service, provider, events):
    add_rider(session)
    charge = service.start_entry_charge(session, "r1")
    assert (charge.purpose, charge.ride_id, charge.amount_cents) == ("entry", "", 5000)
    assert (charge.split.rider_cents, charge.split.company_cents) == (0, 5000)
    assert service.start_entry_charge(session, "r1").charge_id == charge.charge_id
    evento = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, evento) == "applied"
    assert repo.get_rider_account(session, "r1").entry_paid is True
    ledger = PgLedger(session)
    assert (ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (5000, -5000)
    assert ledger.is_balanced() is True
    assert service.on_provider_event(session, evento) == "duplicate"
    assert service.on_provider_event(session, {**evento, "event_id": "evt-outro"}) == "duplicate"
    assert ledger.balance(PgLedger.COMPANY) == 5000
    assert tipos(events, "r1") == ["entry_paid"]
    with pytest.raises(InvalidTransition, match="já foi paga"):
        service.start_entry_charge(session, "r1")
