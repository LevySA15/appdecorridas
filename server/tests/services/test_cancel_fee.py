"""Taxa do cancelamento tardio: valor pela distância andada e cobrança (saldo, devolução do Pix, pendência)."""
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.rides import InvalidTransition, PassengerAccount, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import passenger_block_reason
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride, make_online_rider
from tests.services.test_trips import AGORA, _com_corrida_na_fila, aceitar, pagar

ACEITE = AGORA + 4              # `aceitar` aceita a corrida 4 s depois de pedir
FORA_DA_JANELA = ACEITE + 301   # 300 s de janela grátis, contados do aceite


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
    trips = TripService(payments, dispatch, events, positions=positions)
    return SimpleNamespace(payments=payments, dispatch=dispatch, trips=trips, provider=provider)


def moto_a(session, positions, w, metros=2000.0, **kwargs):
    """Corrida aceita por uma moto que estava a `metros` do ponto de embarque (a origem)."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(metros, 0), now=AGORA)
    return aceitar(session, positions, w, **kwargs)


def saldo(session, cents):
    acc = repo.get_passenger_account(session, "p1")
    repo.save_passenger_account(session, PassengerAccount("p1", acc.unpaid_cents, cents))


def eventos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]


def test_aceite_guarda_a_distancia_inicial_da_moto(session, positions, w):
    moto_a(session, positions, w)
    assert repo.get_ride(session, "ride-1").approach_start_m == pytest.approx(2000, abs=5)


def test_aceite_sem_posicao_da_moto_guarda_nada(session, positions, w):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(300, 0), now=AGORA)
    add_searching_ride(session, "ride-1", "p1", now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    positions.remove("r1")
    w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    assert repo.get_ride(session, "ride-1").approach_start_m is None


def test_corrida_da_fila_comeca_a_aproximacao_ao_ser_promovida(session, positions, w):
    _com_corrida_na_fila(session, positions, w)
    assert repo.get_ride(session, "ride-1").approach_start_m is None        # na fila ainda não começou a vir
    positions.update("r1", pt(150, 0), AGORA + 399)                         # a moto manda posição até o fim da corrida
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    assert repo.get_ride(session, "ride-1").approach_start_m == pytest.approx(150, abs=5)


def test_cancelar_dentro_da_janela_nao_cobra_nada(session, positions, w, events):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", ACEITE + 300)
    assert (resultado.fee_cents, resultado.refund_needed) == (0, False)
    with pytest.raises(LookupError):
        repo.get_cancel_fee(session, "ride-1")
    assert eventos(events, "p1", "cancel_fee") == []


def test_taxa_sai_do_saldo(session, positions, w, events):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    saldo(session, 1000)
    positions.update("r1", pt(500, 0), AGORA + 300)                      # andou 75% do caminho
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.fee_cents, resultado.from_balance_cents, resultado.pending_cents) == (450, 450, 0)
    assert resultado.refund_to is None
    conta = repo.get_passenger_account(session, "p1")
    assert (conta.balance_cents, conta.unpaid_cents) == (550, 0)
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 450 and ledger.balance("balance:p1") == -450
    assert ledger.is_balanced() is True
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.fee_cents, taxa.from_balance_cents, taxa.pending_cents, taxa.reason) == (450, 450, 0, "passenger")
    assert taxa.progress == pytest.approx(0.75, abs=0.01)
    assert eventos(events, "p1", "cancel_fee") == [
        {"ride_id": "ride-1", "fee_cents": 450, "from_balance_cents": 450, "retained_cents": 0,
         "pending_cents": 0, "balance_cents": 550}
    ]
    assert eventos(events, "r1", "ride_cancelled")[-1]["fee_cents"] == 450


def test_saldo_curto_deixa_pendencia_e_bloqueia(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    saldo(session, 100)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)     # moto não saiu do lugar
    assert (resultado.fee_cents, resultado.from_balance_cents, resultado.pending_cents) == (300, 100, 200)
    conta = repo.get_passenger_account(session, "p1")
    assert (conta.balance_cents, conta.unpaid_cents) == (0, 200)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.from_balance_cents, taxa.pending_cents) == (100, 200)
    assert passenger_block_reason(session, "p1") is not None
    assert PgLedger(session).balance("rider:r1") == 100 and PgLedger(session).is_balanced() is True


def _pix_pago(session, positions, w, provider, metros_andados=1000, debt=1000):
    """Pix de R$ 7,00 pago com a moto a 1000 m do ponto (progresso 0,5 = taxa de R$ 4,00)."""
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    acc = repo.get_rider_account(session, "r1")
    acc.cash_debt_cents = debt
    repo.save_rider_account(session, acc)
    aceitar(session, positions, w)
    pagar(session, w)
    positions.update("r1", pt(2000 - metros_andados, 0), AGORA + 300)


def test_pix_pago_sem_saldo_retem_a_taxa_da_devolucao(session, positions, w, provider):
    _pix_pago(session, positions, w, provider)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.fee_cents, resultado.retained_cents, resultado.refund_to) == (400, 400, "pix")
    assert resultado.refund_needed is True and resultado.pending_cents == 0
    charge_id = repo.get_current_charge_id(session, "ride-1")
    assert provider.charges[charge_id].refunded_cents == 300
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 400 and ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == -400
    assert ledger.is_balanced() is True
    acc = repo.get_rider_account(session, "r1")
    assert (acc.cash_debt_cents, acc.debt_reserved_cents) == (1000, 0)       # a dívida abatida voltou


def test_pix_pago_com_saldo_parcial_usa_o_saldo_primeiro(session, positions, w, provider):
    _pix_pago(session, positions, w, provider)
    saldo(session, 150)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.from_balance_cents, resultado.retained_cents, resultado.pending_cents) == (150, 250, 0)
    charge_id = repo.get_current_charge_id(session, "ride-1")
    assert provider.charges[charge_id].refunded_cents == 450
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 400 and ledger.balance("balance:p1") == -150
    assert ledger.is_balanced() is True
    assert repo.get_passenger_account(session, "p1").balance_cents == 0


def test_taxa_com_devolucao_que_nao_chega_retem_e_credita_o_resto(session, positions, w, provider):
    _pix_pago(session, positions, w, provider)
    provider.refund_all_undeliverable = True
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.retained_cents, resultado.refund_to) == (400, "balance")
    assert repo.get_passenger_account(session, "p1").balance_cents == 300
    charge_id = repo.get_current_charge_id(session, "ride-1")
    assert provider.charges[charge_id].refunded_cents == 0
    ledger = PgLedger(session)
    assert ledger.balance("balance:p1") == 300 and ledger.balance("rider:r1") == 400
    assert ledger.is_balanced() is True


def test_taxa_igual_ao_preco_nao_chama_o_provedor_e_o_livro_fecha(session, positions, w, provider):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(0, 0), now=AGORA)
    add_searching_ride(session, "ride-1", "p1", method=PaymentMethod.PIX, price=500, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    pagar(session, w)
    positions.update("r1", pt(0, 0), AGORA + 300)                                       # a moto continua mandando posição
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)    # moto no ponto: R$ 5,00
    assert (resultado.fee_cents, resultado.retained_cents, resultado.refund_to) == (500, 500, "pix")
    charge_id = repo.get_current_charge_id(session, "ride-1")
    assert provider.charges[charge_id].refunded_cents == 0
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 500 and ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == -500
    assert ledger.is_balanced() is True


def test_moto_na_porta_cobra_o_maximo(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    w.trips.arrive(session, "r1", "ride-1", AGORA + 100)
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA).fee_cents == 500


def test_sem_posicao_cobra_o_minimo(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    positions.remove("r1")
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA).fee_cents == 300


def test_cancelar_duas_vezes_nao_cobra_duas_vezes(session, positions, w, events):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    with pytest.raises(InvalidTransition):
        w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA + 1)
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 300
    assert len(eventos(events, "p1", "cancel_fee")) == 1
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED


def test_previa_da_taxa_acompanha_o_que_seria_cobrado(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    positions.update("r1", pt(500, 0), AGORA + 300)
    assert w.trips.cancel_fee_preview(session, "ride-1", ACEITE + 300) == 0          # ainda na janela grátis
    previa = w.trips.cancel_fee_preview(session, "ride-1", FORA_DA_JANELA)
    assert previa == 450
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA).fee_cents == previa
    assert w.trips.cancel_fee_preview(session, "ride-1", FORA_DA_JANELA) == 0        # cancelada: nada a cobrar


def test_cancelar_na_fila_e_sempre_gratis(session, positions, w):
    _com_corrida_na_fila(session, positions, w)
    assert w.trips.cancel_fee_preview(session, "ride-1", AGORA + 10_000) == 0
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 10_000).fee_cents == 0


def test_pix_que_chega_depois_do_cancelamento_tardio_paga_a_taxa_pendente_e_devolve_so_o_resto(
    session, positions, w, provider, events
):
    # O passageiro paga o Pix no banco e cancela quase junto; o cancelamento é processado primeiro. A taxa fica
    # pendente (o Pix ainda não tinha chegado) e, quando o Pix chega, ele cobre a taxa em vez de ser devolvido inteiro.
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    aceitar(session, positions, w)
    positions.update("r1", pt(1000, 0), AGORA + 300)                         # progresso 0,5: taxa de R$ 4,00
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA)
    assert (resultado.fee_cents, resultado.pending_cents, resultado.refund_needed) == (400, 400, False)
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 400
    charge_id = repo.get_current_charge_id(session, "ride-1")
    events.drain()
    assert w.payments.on_provider_event(session, provider.mark_paid(charge_id)) == "refunded"
    assert provider.charges[charge_id].refunded_cents == 300                  # R$ 7,00 pagos menos a taxa de R$ 4,00
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.pending_cents, taxa.paid_later_cents, taxa.retained_cents) == (0, 400, 0)
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 0
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 400 and ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == -400
    assert ledger.is_balanced() is True
    assert passenger_block_reason(session, "p1") is None
    assert eventos(events, "p1", "fee_paid") == [{"ride_id": "ride-1", "amount_cents": 400, "balance_cents": 0}]
    assert eventos(events, "p1", "unblocked") == [{"ride_id": "ride-1"}]
    assert eventos(events, "p1", "payment_refunded")[0]["amount_cents"] == 300
    assert eventos(events, "r1", "payment_received") == [{"ride_id": "ride-1", "amount_cents": 400, "kind": "cancel_fee"}]


def test_pix_atrasado_de_corrida_cancelada_de_graca_continua_sendo_devolvido_inteiro(session, positions, w, provider):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(2000, 0), now=AGORA)
    aceitar(session, positions, w)
    w.trips.cancel_by_passenger(session, "p1", "ride-1", ACEITE + 30)       # dentro da janela: sem taxa
    charge_id = repo.get_current_charge_id(session, "ride-1")
    assert w.payments.on_provider_event(session, provider.mark_paid(charge_id)) == "refunded"
    assert provider.charges[charge_id].refunded_cents == 700
    assert PgLedger(session).balance("rider:r1") == 0


def test_posicao_velha_da_moto_cobra_o_minimo(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    positions.update("r1", pt(500, 0), AGORA + 10)       # andou 75%, mas a última posição é de 295 s atrás
    assert w.trips.cancel_fee_preview(session, "ride-1", FORA_DA_JANELA) == 300
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", FORA_DA_JANELA).fee_cents == 300


def test_posicao_recente_continua_valendo_no_limite_de_30_segundos(session, positions, w):
    moto_a(session, positions, w, method=PaymentMethod.CASH)
    positions.update("r1", pt(500, 0), FORA_DA_JANELA - 30)
    assert w.trips.cancel_fee_preview(session, "ride-1", FORA_DA_JANELA) == 450
    positions.update("r1", pt(500, 0), FORA_DA_JANELA - 31)
    assert w.trips.cancel_fee_preview(session, "ride-1", FORA_DA_JANELA) == 300
