"""Pagar a dívida da taxa por Pix (o motoqueiro bloqueado volta a poder trabalhar)."""
import datetime as dt

import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.rides import InvalidTransition
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.riders import RiderService
from tests.helpers import pt
from tests.helpers_db import make_online_rider

AGORA = 1_800_000_000.0
HOJE = dt.date(2027, 1, 15)


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def service(provider, events):
    return PaymentService(provider, events=events)


def devedor(session, divida=100, reservada=0):
    positions = InMemoryPositionStore()
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    session.get(RiderProfileRow, "r1").online = False       # o bloqueio já o tirou de "estou rodando"
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents, acc.debt_reserved_cents = divida, reservada
    repo.save_rider_account(session, acc)


def avisos(events, tipo):
    return [e.payload for e in events.events if e.user_id == "r1" and e.type == tipo]


def test_cobranca_da_divida_tem_o_valor_a_pagar_sem_a_parte_reservada(session, service):
    devedor(session, divida=100, reservada=40)
    charge = service.start_debt_charge(session, "r1")
    assert (charge.purpose, charge.amount_cents, charge.ride_id, charge.rider_id) == ("debt", 60, "", "r1")
    assert (charge.split.rider_cents, charge.split.company_cents) == (0, 60)
    assert repo.get_charge(session, charge.charge_id).purpose == "debt"


def test_sem_divida_nao_gera_cobranca(session, service):
    devedor(session, divida=0)
    with pytest.raises(InvalidTransition, match="não tem taxa"):
        service.start_debt_charge(session, "r1")
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents, acc.debt_reserved_cents = 40, 40      # tudo reservado a Pix pendente: nada a pagar agora
    repo.save_rider_account(session, acc)
    with pytest.raises(InvalidTransition):
        service.start_debt_charge(session, "r1")


def test_pedir_de_novo_devolve_a_mesma_cobranca(session, service, provider):
    devedor(session)
    primeira = service.start_debt_charge(session, "r1")
    assert service.start_debt_charge(session, "r1").charge_id == primeira.charge_id
    assert len(provider.charges) == 1


def test_pix_da_divida_abate_a_divida_lanca_no_livro_e_avisa(session, service, provider, events):
    devedor(session)
    charge = service.start_debt_charge(session, "r1")
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 0
    ledger = PgLedger(session)
    assert ledger.balance(PgLedger.COMPANY) == 100 and ledger.balance(PgLedger.PROVIDER) == -100
    assert ledger.is_balanced() is True
    assert avisos(events, "debt_paid") == [{"cash_debt_cents": 0, "amount_cents": 100}]
    RiderService(InMemoryPositionStore(), events).go_online(session, "r1", HOJE)      # voltou a poder trabalhar
    assert session.get(RiderProfileRow, "r1").online is True


def test_aviso_repetido_nao_abate_duas_vezes(session, service, provider):
    devedor(session)
    charge = service.start_debt_charge(session, "r1")
    evento = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, evento) == "applied"
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 30                                 # nova dívida depois
    repo.save_rider_account(session, acc)
    assert service.on_provider_event(session, evento) == "duplicate"
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 30
    assert PgLedger(session).balance(PgLedger.COMPANY) == 100


def test_pagar_depois_de_a_divida_ter_diminuido_devolve_o_excesso(session, service, provider):
    devedor(session, divida=100)
    charge = service.start_debt_charge(session, "r1")
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 60                                 # a dívida caiu entre a cobrança e o pagamento
    repo.save_rider_account(session, acc)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 0
    assert provider.charges[charge.charge_id].refunded_cents == 40
    ledger = PgLedger(session)
    assert ledger.balance(PgLedger.COMPANY) == 60 and ledger.balance(PgLedger.PROVIDER) == -60
    assert ledger.is_balanced() is True


def test_pagar_quando_nao_deve_mais_nada_devolve_tudo(session, service, provider):
    devedor(session, divida=100)
    charge = service.start_debt_charge(session, "r1")
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = 0
    repo.save_rider_account(session, acc)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    assert provider.charges[charge.charge_id].refunded is True
    assert PgLedger(session).balance(PgLedger.COMPANY) == 0


def test_pagar_a_divida_nao_mexe_na_entrada_nem_na_contagem_de_corridas(session, service, provider):
    devedor(session)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 4
    repo.save_rider_account(session, acc)
    charge = service.start_debt_charge(session, "r1")
    service.on_provider_event(session, provider.mark_paid(charge.charge_id))
    acc = repo.get_rider_account(session, "r1")
    assert (acc.completed_rides, acc.entry_paid) == (4, False)
