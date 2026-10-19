"""Recurso da taxa de cancelamento: o passageiro pede, o administrador decide."""
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.passenger_money import AppealNotAllowed
from app.services.quotes import passenger_block_reason
from app.services.trips import NotYourRide
from tests.helpers_db import add_passenger
from tests.services.helpers_money import (
    FORA_DA_JANELA,
    avisos,
    com_pendencia,
    make_world,
    pix_pago_e_cancelado,
)

TEXTO = "A moto ficou parada na esquina."


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


def test_recurso_abre_uma_vez_e_avisa_o_administrador(session, positions, w, events, dono):
    com_pendencia(session, positions, w)
    events.drain()
    w.money.file_appeal(session, "p1", "ride-1", f"  {TEXTO}  ", FORA_DA_JANELA + 60)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.appeal_state, taxa.appeal_text, taxa.appealed_at) == ("open", TEXTO, FORA_DA_JANELA + 60)
    assert avisos(events, dono, "appeal_opened") == [{"ride_id": "ride-1"}]
    assert "fee_appeal_opened" in [k for k, _ in repo.ride_events(session, "ride-1")]
    with pytest.raises(AppealNotAllowed, match="já pediu"):
        w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 61)


def test_recurso_de_outra_pessoa_e_recusado(session, positions, w):
    com_pendencia(session, positions, w)
    add_passenger(session, "p2", "+5575900000022")
    with pytest.raises(NotYourRide):
        w.money.file_appeal(session, "p2", "ride-1", TEXTO, FORA_DA_JANELA)
    assert repo.get_cancel_fee(session, "ride-1").appeal_state == "none"


def test_recurso_depois_de_7_dias_e_recusado_e_no_ultimo_segundo_ainda_vale(session, positions, w):
    com_pendencia(session, positions, w)
    criada = repo.get_cancel_fee(session, "ride-1").created_at
    with pytest.raises(AppealNotAllowed, match="prazo"):
        w.money.file_appeal(session, "p1", "ride-1", TEXTO, criada + 604_800 + 1)
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, criada + 604_800)
    assert repo.get_cancel_fee(session, "ride-1").appeal_state == "open"


def test_recurso_sem_taxa_e_recusado(session, w):
    add_passenger(session)
    with pytest.raises(LookupError):
        w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA)


@pytest.mark.parametrize("texto", ["", "  ", "oi", "x" * 501])
def test_texto_curto_ou_longo_demais_e_recusado(session, positions, w, texto):
    com_pendencia(session, positions, w)
    with pytest.raises(ValueError, match="3 a 500"):
        w.money.file_appeal(session, "p1", "ride-1", texto, FORA_DA_JANELA)
    assert repo.get_cancel_fee(session, "ride-1").appeal_state == "none"


def test_recurso_aceito_devolve_ao_saldo_o_que_foi_cobrado(session, positions, w, provider, events, dono):
    pix_pago_e_cancelado(session, positions, w, balance_cents=150)       # taxa 400: 150 do saldo + 250 retidos do Pix
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 60)
    events.drain()
    w.money.decide_appeal(session, dono, "ride-1", True, "Procede.", FORA_DA_JANELA + 3600)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.appeal_state, taxa.credited_back_cents, taxa.decided_by, taxa.decision_note) == (
        "accepted", 400, dono, "Procede.",
    )
    assert repo.get_passenger_account(session, "p1").balance_cents == 400
    ledger = PgLedger(session)
    assert ledger.balance("balance:p1") == 400
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 400
    assert ledger.balance(PgLedger.COMPANY) == -400
    assert ledger.balance("rider:r1") == 400                           # o motoqueiro fica com a taxa
    assert ledger.is_balanced() is True
    assert avisos(events, "p1", "appeal_decided") == [{"ride_id": "ride-1", "decision": "accept", "credited_cents": 400}]


def test_recurso_aceito_com_pendencia_perdoa_e_desbloqueia(session, positions, w, events, dono):
    com_pendencia(session, positions, w, balance_cents=100)
    # com_pendencia já cancelou: a taxa de R$ 3,00 pegou os R$ 1,00 do saldo e deixou R$ 2,00 pendentes
    assert repo.get_cancel_fee(session, "ride-1").pending_cents == 200
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 60)
    events.drain()
    w.money.decide_appeal(session, dono, "ride-1", True, "", FORA_DA_JANELA + 120)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.pending_cents, taxa.waived_cents, taxa.credited_back_cents) == (0, 200, 100)
    conta = repo.get_passenger_account(session, "p1")
    assert (conta.unpaid_cents, conta.balance_cents) == (0, 100)
    assert avisos(events, "p1", "unblocked") == [{"ride_id": "ride-1"}]
    assert passenger_block_reason(session, "p1") is None
    assert PgLedger(session).is_balanced() is True


def test_recurso_aceito_depois_de_pagar_a_pendencia_devolve_tudo_ao_saldo(session, positions, w, provider, dono):
    com_pendencia(session, positions, w)                                # R$ 3,00 pendentes, sem saldo
    charge = w.money.pay_pending(session, "p1", FORA_DA_JANELA + 10)
    w.payments.on_provider_event(session, provider.mark_paid(charge.charge_id))
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 60)
    w.money.decide_appeal(session, dono, "ride-1", True, "", FORA_DA_JANELA + 120)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.paid_later_cents, taxa.credited_back_cents, taxa.waived_cents) == (300, 300, 0)
    assert repo.get_passenger_account(session, "p1").balance_cents == 300
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300 and ledger.balance(PgLedger.COMPANY) == -300
    assert ledger.is_balanced() is True


def test_recurso_recusado_nao_muda_nada_de_dinheiro(session, positions, w, events, dono):
    com_pendencia(session, positions, w, balance_cents=100)
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 60)
    antes = (repo.get_passenger_account(session, "p1"), PgLedger(session).balance("rider:r1"))
    events.drain()
    w.money.decide_appeal(session, dono, "ride-1", False, "Não procede.", FORA_DA_JANELA + 120)
    taxa = repo.get_cancel_fee(session, "ride-1")
    assert (taxa.appeal_state, taxa.pending_cents, taxa.credited_back_cents, taxa.decision_note) == (
        "rejected", 200, 0, "Não procede.",
    )
    assert (repo.get_passenger_account(session, "p1"), PgLedger(session).balance("rider:r1")) == antes
    assert avisos(events, "p1", "appeal_decided") == [{"ride_id": "ride-1", "decision": "reject", "credited_cents": 0}]
    assert avisos(events, "p1", "unblocked") == []


def test_decidir_duas_vezes_e_recusado(session, positions, w, dono):
    com_pendencia(session, positions, w)
    w.money.file_appeal(session, "p1", "ride-1", TEXTO, FORA_DA_JANELA + 60)
    w.money.decide_appeal(session, dono, "ride-1", False, "", FORA_DA_JANELA + 120)
    with pytest.raises(AppealNotAllowed, match="já foi decidido"):
        w.money.decide_appeal(session, dono, "ride-1", True, "", FORA_DA_JANELA + 130)
    assert repo.get_cancel_fee(session, "ride-1").appeal_state == "rejected"


def test_decidir_recurso_que_nao_foi_aberto_e_recusado(session, positions, w, dono):
    com_pendencia(session, positions, w)
    with pytest.raises(AppealNotAllowed, match="não foi pedido"):
        w.money.decide_appeal(session, dono, "ride-1", True, "", FORA_DA_JANELA + 120)
    with pytest.raises(LookupError):
        w.money.decide_appeal(session, dono, "ride-9", True, "", FORA_DA_JANELA + 120)
