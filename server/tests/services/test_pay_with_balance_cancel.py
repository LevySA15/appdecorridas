"""Cancelar, sair da fila, não aparecer e recorrer numa corrida paga com o saldo: o dinheiro volta sempre ao saldo."""
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride, make_online_rider
from tests.services.helpers_money import FORA_DA_JANELA, make_world, recarregar
from tests.services.test_trips import AGORA, aceitar

ACEITE = AGORA + 4


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


@pytest.fixture()
def dono(session):
    repo.add_user(session, user_id="a1", phone="+5575900000099", name="Dono", role="admin")
    return "a1"


def corrida_paga(session, positions, w, saldo=2000, andados=900, divida=0):
    """Passageiro com `saldo` paga a corrida de R$ 7,00 com ele; a moto (a 2000 m) já andou `andados` metros."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    if divida:
        acc = repo.get_rider_account(session, "r1")
        acc.cash_debt_cents = divida
        repo.save_rider_account(session, acc)
    recarregar(session, w, saldo)
    ride = aceitar(session, positions, w, pay_with_balance=True)
    assert ride.pix_paid is True
    positions.update("r1", pt(2000 - andados, 0), AGORA + 300)
    return ride


def so_recarga_no_provedor(provider):
    assert [c.purpose for c in provider.charges.values()] == ["topup"]
    assert all(c.refunded_cents == 0 for c in provider.charges.values())


def test_cancelar_dentro_da_janela_devolve_tudo_ao_saldo_sem_chamar_o_provedor(session, positions, w, provider):
    corrida_paga(session, positions, w)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", ACEITE + 30)
    assert (resultado.fee_cents, resultado.refund_needed, resultado.refund_to) == (0, True, "balance")
    assert repo.get_passenger_account(session, "p1").balance_cents == 2000
    so_recarga_no_provedor(provider)
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (2000, 0, 0)
    assert ledger.is_balanced() is True
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 2000


def test_cancelar_tarde_retem_a_taxa_e_devolve_o_resto_ao_saldo(session, positions, w, provider):
    corrida_paga(session, positions, w, saldo=800)         # sobram R$ 1,00 depois de pagar; a taxa de R$ 4,00 passa disso
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.fee_cents, resultado.from_balance_cents, resultado.retained_cents, resultado.pending_cents) == (
        400, 100, 300, 0,
    )
    assert resultado.refund_to == "balance"
    assert repo.get_passenger_account(session, "p1").balance_cents == 400       # 100 - 100 + (700 - 300)
    so_recarga_no_provedor(provider)
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (400, 400, 0)
    assert ledger.is_balanced() is True
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.from_balance_cents, taxa.retained_cents, taxa.pending_cents) == (100, 300, 0)
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 400


def test_taxa_sai_do_outro_saldo_quando_ele_cobre_e_a_corrida_volta_inteira(session, positions, w):
    corrida_paga(session, positions, w, saldo=2000)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.fee_cents, resultado.from_balance_cents, resultado.retained_cents) == (400, 400, 0)
    assert repo.get_passenger_account(session, "p1").balance_cents == 1600     # 2000 - 400 de taxa
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY)) == (400, 0)
    assert ledger.is_balanced() is True


def test_passageiro_que_nao_aparece_paga_cinco_reais_e_o_resto_volta_ao_saldo(session, positions, w, provider):
    corrida_paga(session, positions, w, saldo=700)          # o saldo zera ao pagar
    w.trips.arrive(session, "r1", "ride-1", AGORA + 100)
    resultado = w.payments.cancel_after_arrival_timeout(session, "ride-1", AGORA + 100 + 300)
    assert (resultado.fee_cents, resultado.retained_cents, resultado.refund_to) == (500, 500, "balance")
    assert repo.get_passenger_account(session, "p1").balance_cents == 200
    so_recarga_no_provedor(provider)
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r1")) == (200, 500)
    assert ledger.is_balanced() is True


def test_sair_da_fila_devolve_ao_saldo_e_o_novo_aceite_cobra_de_novo(session, positions, w, provider):
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    recarregar(session, w, 2000)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0", destination=pt(300, 0))
    w.trips.arrive(session, "r1", "ride-0", AGORA + 50)
    w.trips.confirm_helmet(session, "r1", "ride-0", AGORA + 51)
    w.trips.start_trip(session, "r1", "ride-0", "4821", AGORA + 52)
    positions.update("r1", pt(150, 0), now=AGORA + 100)
    add_searching_ride(session, "ride-1", "p1", now=AGORA + 100, pay_with_balance=True)
    assert w.dispatch.offer_next(session, "ride-1", AGORA + 100) == "r1"
    assert w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101).state is RideState.QUEUED
    assert repo.get_passenger_account(session, "p1").balance_cents == 1300          # já pagou, mesmo na fila
    assert w.payments.release_queued_ride(session, "ride-1", AGORA + 200) is True
    assert repo.get_passenger_account(session, "p1").balance_cents == 2000
    assert repo.get_current_charge_id(session, "ride-1") is None
    so_recarga_no_provedor(provider)
    make_online_rider(session, positions, 2, pt(200, 0), now=AGORA + 205)
    assert w.dispatch.offer_next(session, "ride-1", AGORA + 210) == "r2"
    outra = w.dispatch.accept_offer(session, "r2", "ride-1", AGORA + 214)
    assert outra.pix_paid is True and outra.pay_with_balance is True
    assert repo.get_passenger_account(session, "p1").balance_cents == 1300          # pagou de novo, uma vez só
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance("rider:r2")) == (1300, 600)
    assert ledger.is_balanced() is True
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 1300


def test_divida_abatida_no_aceite_volta_no_cancelamento(session, positions, w):
    corrida_paga(session, positions, w, divida=60)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 0
    w.trips.cancel_by_passenger(session, "p1", "ride-1", ACEITE + 30)
    acc = repo.get_rider_account(session, "r1")
    assert (acc.cash_debt_cents, acc.debt_reserved_cents) == (60, 0)
    assert PgLedger(session).is_balanced() is True


def test_recurso_aceito_de_corrida_paga_com_saldo_devolve_o_que_foi_cobrado(session, positions, w, events, dono):
    corrida_paga(session, positions, w, saldo=800)
    w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)       # taxa 400: 100 do saldo + 300 retidos
    w.money.file_appeal(session, "p1", "ride-1", "A moto ficou parada na esquina.", FORA_DA_JANELA + 60)
    w.money.decide_appeal(session, dono, "ride-1", True, "Procede.", FORA_DA_JANELA + 3600)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.appeal_state, taxa.credited_back_cents) == ("accepted", 400)
    assert repo.get_passenger_account(session, "p1").balance_cents == 800       # tudo de volta, como se nada tivesse acontecido
    ledger = PgLedger(session)
    assert (ledger.balance("balance:p1"), ledger.balance(PgLedger.COMPANY), ledger.balance("rider:r1")) == (800, -400, 400)
    assert ledger.is_balanced() is True
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 800
