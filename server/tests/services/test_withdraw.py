"""Sacar o saldo por Pix."""
import dataclasses

import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.models import WithdrawalRow
from app.db.pg_ledger import PgLedger
from app.domain.config import BalanceConfig
from app.domain.payments import PayoutFailed
from app.domain.rides import PassengerAccount
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.passenger_money import PassengerMoneyService, WithdrawDisabled
from app.services.quotes import NotAllowed
from tests.helpers_db import add_passenger
from tests.services.helpers_money import LIGADA, com_pendencia, make_world, recarregar

CPF = "529.982.247-25"
AGORA = 1_800_000_000.0


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
def money(w, events):
    """O serviço com o saque ligado (nasce desligado)."""
    ligada = dataclasses.replace(
        LIGADA, balance=BalanceConfig(topup_enabled=True, topup_min_cents=100, topup_max_cents=20_000, withdraw_enabled=True)
    )
    return PassengerMoneyService(w.payments, events, ligada)


def eventos(events, user_id, tipo):
    return [e.payload for e in events.events if e.user_id == user_id and e.type == tipo]


def com_saldo(session, w, cents=2000):
    add_passenger(session)
    recarregar(session, w, cents)


def nada_mudou(session, provider, saldo=2000):
    session.expire_all()
    assert repo.get_passenger_account(session, "p1").balance_cents == saldo
    assert PgLedger(session).balance("balance:p1") == saldo
    assert repo.list_withdrawals(session) == [] and provider.payouts == {}


def test_saque_desligado_e_recusado(session, w, provider):
    com_saldo(session, w)
    with pytest.raises(WithdrawDisabled):
        w.money.withdraw(session, "p1", 1500, CPF, AGORA)
    nada_mudou(session, provider)


def test_saque_debita_lanca_no_livro_e_manda_o_pix(session, w, money, provider, events):
    com_saldo(session, w)
    events.drain()
    saque = money.withdraw(session, "p1", 1500, CPF, AGORA)
    assert (saque.amount_cents, saque.key_kind, saque.key_masked, saque.passenger_id) == (1500, "cpf", "final 4725", "p1")
    assert repo.get_passenger_account(session, "p1").balance_cents == 500
    ledger = PgLedger(session)
    assert ledger.balance("balance:p1") == 500
    assert ledger.balance(PgLedger.PROVIDER) == -500          # entraram 2000 na recarga e saíram 1500
    assert ledger.is_balanced() is True
    assert provider.payouts == {saque.withdrawal_id: ("52998224725", 1500)}
    assert repo.list_withdrawals(session) == [saque]
    assert queries.passenger_balances_total(session) == queries.ledger_balances_total(session) == 500
    assert eventos(events, "p1", "balance_changed") == [{"balance_cents": 500}]
    assert eventos(events, "p1", "withdrawal_done") == [
        {"withdrawal_id": saque.withdrawal_id, "amount_cents": 1500, "balance_cents": 500}
    ]


def test_saque_do_saldo_inteiro_zera_o_saldo(session, w, money):
    com_saldo(session, w)
    money.withdraw(session, "p1", 2000, CPF, AGORA)
    assert repo.get_passenger_account(session, "p1").balance_cents == 0


def test_saque_maior_que_o_saldo_e_recusado_e_nao_muda_nada(session, w, money, provider):
    com_saldo(session, w)
    with pytest.raises(NotAllowed, match="saldo é menor"):
        money.withdraw(session, "p1", 2001, CPF, AGORA)
    nada_mudou(session, provider)


@pytest.mark.parametrize("valor", [499, 0, -100, 50_001])
def test_saque_fora_dos_limites_e_recusado(session, w, money, provider, valor):
    com_saldo(session, w)
    repo.save_passenger_account(session, PassengerAccount("p1", 0, 60_000))
    with pytest.raises(ValueError, match=r"R\$ 5,00 a R\$ 500,00"):
        money.withdraw(session, "p1", valor, CPF, AGORA)
    assert provider.payouts == {} and repo.list_withdrawals(session) == []


@pytest.mark.parametrize("chave", ["", "abc", "529.982.247-26", "sem-arroba", "(75) 98851-0824"])
def test_chave_invalida_e_recusada_antes_de_debitar(session, w, money, provider, chave):
    com_saldo(session, w)
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        money.withdraw(session, "p1", 1500, chave, AGORA)
    nada_mudou(session, provider)


def test_saque_com_taxa_pendente_e_recusado(session, positions, w, money, provider):
    com_pendencia(session, positions, w)            # taxa de R$ 3,00 pendente (sem saldo)
    recarregar(session, w, 2000)
    assert repo.pending_cancel_fee(session, "p1") is not None
    with pytest.raises(NotAllowed, match="pendente"):
        money.withdraw(session, "p1", 1500, CPF, AGORA)
    assert provider.payouts == {} and repo.list_withdrawals(session) == []


def test_provedor_fora_do_ar_nao_deixa_rastro(session, w, money, provider, events):
    com_saldo(session, w)
    provider.fail_payouts = True
    events.drain()
    with pytest.raises(PayoutFailed):
        with session.begin_nested():            # o que o `Runtime.run` faz: a unidade de trabalho inteira é desfeita
            money.withdraw(session, "p1", 1500, CPF, AGORA)
    nada_mudou(session, provider)
    assert eventos(events, "p1", "withdrawal_done") == []


def test_dois_saques_seguidos_nao_passam_do_saldo(session, w, money):
    com_saldo(session, w)
    money.withdraw(session, "p1", 1500, CPF, AGORA)
    with pytest.raises(NotAllowed, match="saldo é menor"):
        money.withdraw(session, "p1", 1500, CPF, AGORA + 1)
    assert repo.get_passenger_account(session, "p1").balance_cents == 500
    assert len(repo.list_withdrawals(session)) == 1


def test_chave_inteira_nao_fica_no_banco(session, w, money):
    com_saldo(session, w)
    saque = money.withdraw(session, "p1", 1500, CPF, AGORA)
    linha = session.get(WithdrawalRow, saque.withdrawal_id)
    guardado = " ".join(str(v) for v in (linha.key_kind, linha.key_masked, linha.provider_ref, linha.passenger_id))
    assert "52998224725" not in guardado and "529" not in guardado


def test_o_saque_fica_gravado_antes_de_o_pix_sair(session, w, money, provider, monkeypatch):
    # Só o commit pode vir depois do Pix: se gravar o saque falhar, o Pix nem pode ter saído (senão o dinheiro
    # sai e o saldo continua inteiro, e o passageiro saca de novo).
    com_saldo(session, w)

    def falha(*args, **kwargs):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(repo, "add_withdrawal", falha)
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            money.withdraw(session, "p1", 1500, CPF, AGORA)
    assert provider.payouts == {}
