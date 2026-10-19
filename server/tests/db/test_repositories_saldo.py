import pytest

from app.db import queries
from app.db import repositories as repo
from app.domain.balance import CancelFee
from app.domain.payments import PixCharge, Split
from app.domain.rides import PassengerAccount
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def _taxa(ride_id="ride-1", **extra) -> CancelFee:
    dados = dict(
        ride_id=ride_id, passenger_id="p1", rider_id="r1", fee_cents=400, reason="passenger", created_at=1000.0,
        traveled_m=1200.0, from_balance_cents=100, pending_cents=300,
    ) | extra
    return CancelFee(**dados)


def _duas_corridas(session) -> None:
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    # a segunda corrida de outro dia (a primeira foi cancelada) para ter duas taxas do mesmo passageiro
    repo_ride = repo.get_ride(session, "ride-1")
    repo_ride.state = repo_ride.state.CANCELLED
    repo.save_ride(session, repo_ride)
    add_accepted_ride(session, ride_id="ride-2")


def test_saldo_do_passageiro_vai_e_volta_pelo_repositorio(session):
    add_passenger(session)
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=200, balance_cents=700))
    session.expire_all()
    assert repo.get_passenger_account(session, "p1") == PassengerAccount("p1", unpaid_cents=200, balance_cents=700)


def test_distancia_inicial_da_aproximacao_vai_e_volta_com_a_corrida(session):
    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session)
    ride.approach_start_m = 1850.5
    repo.save_ride(session, ride)
    session.expire_all()
    assert repo.get_ride(session, "ride-1").approach_start_m == 1850.5


def test_taxa_de_cancelamento_vai_e_volta_com_todos_os_campos(session):
    _duas_corridas(session)
    taxa = _taxa(
        appeal_state="open", appeal_text="A moto estava parada.", appealed_at=1100.0, decided_at=None, waived_cents=0
    )
    repo.add_cancel_fee(session, taxa)
    session.expire_all()
    assert repo.get_cancel_fee(session, "ride-1") == taxa
    taxa.appeal_state, taxa.decided_at, taxa.decided_by, taxa.decision_note = "accepted", 1200.0, "p1", "Procede."
    taxa.waived_cents, taxa.pending_cents, taxa.credited_back_cents = 300, 0, 100
    repo.save_cancel_fee(session, taxa)
    session.expire_all()
    assert repo.get_cancel_fee(session, "ride-1") == taxa


def test_taxa_que_nao_existe_da_erro_de_nao_encontrado(session):
    _duas_corridas(session)
    with pytest.raises(LookupError):
        repo.get_cancel_fee(session, "ride-9")


def test_pendencia_mais_antiga_vem_primeiro_e_as_pagas_ficam_de_fora(session):
    _duas_corridas(session)
    repo.add_cancel_fee(session, _taxa("ride-2", created_at=2000.0))
    repo.add_cancel_fee(session, _taxa("ride-1", created_at=1000.0))
    assert repo.pending_cancel_fee(session, "p1").ride_id == "ride-1"
    quitada = repo.get_cancel_fee(session, "ride-1")
    quitada.paid_later_cents, quitada.pending_cents = 300, 0
    repo.save_cancel_fee(session, quitada)
    assert repo.pending_cancel_fee(session, "p1").ride_id == "ride-2"
    assert repo.pending_cancel_fee(session, "outro") is None


def test_taxas_recentes_respeitam_o_corte_e_vem_da_mais_nova_para_a_mais_antiga(session):
    _duas_corridas(session)
    repo.add_cancel_fee(session, _taxa("ride-1", created_at=1000.0))
    repo.add_cancel_fee(session, _taxa("ride-2", created_at=2000.0))
    assert [t.ride_id for t in repo.recent_cancel_fees(session, "p1", since=0.0)] == ["ride-2", "ride-1"]
    assert [t.ride_id for t in repo.recent_cancel_fees(session, "p1", since=1500.0)] == ["ride-2"]


def test_recarga_sem_corrida_e_sem_motoqueiro_vai_e_volta(session):
    add_passenger(session)
    recarga = PixCharge(
        charge_id="ch-7", ride_id="", rider_id="", amount_cents=2000, split=Split(0, 2000, 0), purpose="topup",
        passenger_id="p1", br_code="fake",
    )
    repo.add_charge(session, recarga)
    session.expire_all()
    lida = repo.get_charge(session, "ch-7")
    assert (lida.ride_id, lida.rider_id, lida.passenger_id, lida.purpose) == ("", "", "p1", "topup")
    assert repo.find_open_topup_charge(session, "p1").charge_id == "ch-7"
    lida.paid = True
    repo.save_charge(session, lida)
    assert repo.find_open_topup_charge(session, "p1") is None


def test_procura_da_cobranca_aberta_so_acha_a_nao_paga_do_proposito_pedido(session):
    _duas_corridas(session)
    taxa = PixCharge(
        charge_id="ch-8", ride_id="ride-2", rider_id="r1", amount_cents=300, split=Split(300, 0, 0), purpose="fee"
    )
    repo.add_charge(session, taxa)
    assert repo.find_open_charge(session, "ride-2", "fee").charge_id == "ch-8"
    assert repo.find_open_charge(session, "ride-2", "end") is None
    assert repo.find_open_charge(session, "ride-1", "fee") is None
    taxa.paid = True
    repo.save_charge(session, taxa)
    assert repo.find_open_charge(session, "ride-2", "fee") is None


def test_lista_de_recursos_junta_os_nomes_e_filtra_pela_situacao(session):
    _duas_corridas(session)
    repo.add_cancel_fee(session, _taxa("ride-1", appeal_state="open", appeal_text="Não foi culpa minha.", appealed_at=1100.0))
    repo.add_cancel_fee(session, _taxa("ride-2", created_at=2000.0))
    abertos = queries.list_appeals(session, "open", limit=10, offset=0)
    assert [a.ride_id for a in abertos] == ["ride-1"]
    item = abertos[0]
    assert (item.passenger_name, item.rider_name) == ("Passageiro p1", "Motoqueiro r1")
    assert (item.fee_cents, item.appeal_text, item.appeal_state) == (400, "Não foi culpa minha.", "open")
    assert queries.list_appeals(session, "accepted", limit=10, offset=0) == []


def test_totais_do_saldo_comparam_banco_e_livro(session):
    from app.db.pg_ledger import PgLedger

    add_passenger(session)
    assert queries.passenger_balances_total(session) == 0 and queries.ledger_balances_total(session) == 0
    repo.save_passenger_account(session, PassengerAccount("p1", balance_cents=2000))
    PgLedger(session).post_topup("ch-9", "p1", 2000)
    assert queries.passenger_balances_total(session) == 2000 == queries.ledger_balances_total(session)


def test_taxas_inconsistentes_aparecem_na_conferencia(session):
    _duas_corridas(session)
    repo.add_cancel_fee(session, _taxa("ride-1"))
    assert queries.inconsistent_fee_ids(session) == []
