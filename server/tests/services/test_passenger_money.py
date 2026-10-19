"""Pagar a taxa pendente (saldo ou Pix) e recarregar o saldo."""
import dataclasses
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.pg_ledger import PgLedger
from app.domain.balance import waive_pending
from app.domain.config import BalanceConfig
from app.domain.dispatch import ReservationBook
from app.domain.rides import PassengerAccount
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.passenger_money import NothingToPay, PassengerMoneyService, TopupDisabled
from app.services.payments import PaymentService
from app.services.quotes import passenger_block_reason
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, make_online_rider
from tests.services.test_trips import AGORA, aceitar

FORA_DA_JANELA = AGORA + 4 + 301
LIGADA = dataclasses.replace(AppConfig.defaults(), balance=BalanceConfig(topup_enabled=True))


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
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, provider=provider,
        trips=TripService(payments, dispatch, events, positions=positions),
        money=PassengerMoneyService(payments, events, LIGADA),
        desligado=PassengerMoneyService(payments, events),
    )


def com_pendencia(session, positions, w):
    """Passageiro sem saldo cancela tarde uma corrida em dinheiro: R$ 3,00 de taxa pendente."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert resultado.pending_cents == 300


def saldo(session, cents):
    acc = repo.get_passenger_account(session, "p1")
    repo.save_passenger_account(session, PassengerAccount("p1", acc.unpaid_cents, cents))


def avisos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]


def test_pendencia_paga_pelo_saldo_desbloqueia(session, positions, w, events):
    com_pendencia(session, positions, w)
    saldo(session, 500)
    events.drain()
    assert w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10) is None
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.pending_cents, taxa.paid_later_cents) == (0, 300)
    conta = repo.get_passenger_account(session, "p1")
    assert (conta.unpaid_cents, conta.balance_cents) == (0, 200)
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300 and ledger.balance("balance:p1") == -300
    assert ledger.is_balanced() is True
    assert avisos(events, "p1", "fee_paid") == [{"ride_id": "ride-1", "amount_cents": 300, "balance_cents": 200}]
    assert avisos(events, "p1", "unblocked") == [{"ride_id": "ride-1"}]
    assert passenger_block_reason(session, "p1") is None


def test_pendencia_sem_saldo_gera_cobranca_pix_do_valor_inteiro(session, positions, w):
    com_pendencia(session, positions, w)
    saldo(session, 100)                                     # saldo menor que a pendência não se mistura com o Pix
    charge = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    assert (charge.purpose, charge.amount_cents, charge.ride_id, charge.rider_id) == ("fee", 300, "ride-1", "r1")
    assert (charge.split.rider_cents, charge.split.company_cents) == (300, 0)
    assert charge.br_code
    assert repo.get_passenger_account(session, "p1").balance_cents == 100
    assert repo.get_charge(session, charge.charge_id).purpose == "fee"


def test_pedir_a_cobranca_duas_vezes_devolve_a_mesma(session, positions, w, provider):
    com_pendencia(session, positions, w)
    primeira = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    segunda = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 20)
    assert segunda.charge_id == primeira.charge_id and len(provider.charges) == 1


def test_pagar_o_pix_da_taxa_quita_e_desbloqueia(session, positions, w, provider, events):
    com_pendencia(session, positions, w)
    charge = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    events.drain()
    assert w.payments.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.pending_cents, taxa.paid_later_cents) == (0, 300)
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 0
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300 and ledger.balance(PgLedger.PROVIDER) == -300
    assert ledger.is_balanced() is True
    assert avisos(events, "p1", "fee_paid") == [{"ride_id": "ride-1", "amount_cents": 300, "balance_cents": 0}]
    assert avisos(events, "p1", "unblocked") == [{"ride_id": "ride-1"}]
    assert avisos(events, "r1", "payment_received") == [{"ride_id": "ride-1", "amount_cents": 300, "kind": "cancel_fee"}]
    assert passenger_block_reason(session, "p1") is None


def test_aviso_repetido_da_taxa_nao_paga_duas_vezes(session, positions, w, provider):
    com_pendencia(session, positions, w)
    charge = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    evento = provider.mark_paid(charge.charge_id)
    assert w.payments.on_provider_event(session, evento) == "applied"
    assert w.payments.on_provider_event(session, evento) == "duplicate"
    assert repo.get_cancel_fee(session, "ride-1").paid_later_cents == 300
    assert PgLedger(session).balance("rider:r1") == 300


@pytest.mark.parametrize("nao_chega, esperado_saldo", [(False, 0), (True, 300)])
def test_taxa_paga_depois_de_perdoada_volta_para_o_passageiro(session, positions, w, provider, nao_chega, esperado_saldo):
    com_pendencia(session, positions, w)
    charge = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    taxa = repo.get_cancel_fee(session, "ride-1")                   # o recurso foi aceito antes de o Pix chegar
    waive_pending(taxa)
    repo.save_cancel_fee(session, taxa)
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=0))
    provider.refund_all_undeliverable = nao_chega
    assert w.payments.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    assert repo.get_cancel_fee(session, "ride-1").paid_later_cents == 0
    conta = repo.get_passenger_account(session, "p1")
    assert (conta.unpaid_cents, conta.balance_cents) == (0, esperado_saldo)
    assert provider.charges[charge.charge_id].refunded_cents == (0 if nao_chega else 300)
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.is_balanced() is True


def test_sem_pendencia_nao_ha_o_que_pagar(session, w):
    add_passenger(session)
    with pytest.raises(NothingToPay):
        w.money.pay_pending(session, "p1", AGORA)


def test_recarga_desligada_por_padrao_recusa_com_erro_claro(session, w):
    add_passenger(session)
    assert BalanceConfig().topup_enabled is False
    with pytest.raises(TopupDisabled, match="ainda não está disponível"):
        w.desligado.topup(session, "p1", 2000, AGORA)


@pytest.mark.parametrize("valor", [999, 20_001, 0, -500])
def test_recarga_fora_dos_limites_e_recusada(session, w, valor):
    add_passenger(session)
    with pytest.raises(ValueError, match="R\\$ 10,00 a R\\$ 200,00"):
        w.money.topup(session, "p1", valor, AGORA)


def test_recarga_paga_credita_o_saldo_e_o_livro_fecha(session, w, provider, events):
    add_passenger(session)
    charge = w.money.topup(session, "p1", 2000, AGORA)
    assert (charge.purpose, charge.passenger_id, charge.rider_id, charge.ride_id) == ("topup", "p1", "", "")
    assert w.money.topup(session, "p1", 2000, AGORA + 1).charge_id == charge.charge_id
    assert w.money.topup(session, "p1", 3000, AGORA + 2).charge_id != charge.charge_id
    events.drain()
    assert w.payments.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_passenger_account(session, "p1").balance_cents == 2000
    ledger = PgLedger(session)
    assert ledger.balance("balance:p1") == 2000 and ledger.balance(PgLedger.PROVIDER) == -2000
    assert ledger.is_balanced() is True
    assert avisos(events, "p1", "balance_changed") == [{"balance_cents": 2000}]


def test_recarga_repetida_credita_uma_vez(session, w, provider):
    add_passenger(session)
    charge = w.money.topup(session, "p1", 2000, AGORA)
    evento = provider.mark_paid(charge.charge_id)
    assert w.payments.on_provider_event(session, evento) == "applied"
    assert w.payments.on_provider_event(session, evento) == "duplicate"
    assert repo.get_passenger_account(session, "p1").balance_cents == 2000
