import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import DebtState
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    accept,
    mark_arrived,
)
from app.domain.types import PaymentMethod
from app.services.payments import PaymentService
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider

FEE = 100


class RefundFalha(FakePaymentProvider):
    def refund(self, charge_id: str) -> None:
        raise RuntimeError("provedor fora do ar")


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def service(provider):
    return PaymentService(provider)


def mundo(session, debt=1000, busy=False, method=PaymentMethod.PIX):
    add_passenger(session)
    add_rider(session, debt_cents=debt)
    return add_accepted_ride(session, busy=busy, method=method)


def divida(session, rider_id="r1"):
    acc = repo.get_rider_account(session, rider_id)
    return acc.cash_debt_cents, acc.debt_reserved_cents


def test_cobranca_reserva_a_divida_sem_abater(session, service):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert divida(session) == (1000, 300)
    assert charge.split.debt_paid_cents == 300
    assert charge.debt_state is DebtState.RESERVED
    assert repo.get_current_charge_id(session, "ride-1") == charge.charge_id
    assert repo.get_charge(session, charge.charge_id) == charge


def test_pedir_a_cobranca_de_novo_devolve_a_mesma(session, service, provider):
    mundo(session)
    primeira = service.start_pix_charge(session, "ride-1", FEE)
    segunda = service.start_pix_charge(session, "ride-1", FEE)
    assert segunda.charge_id == primeira.charge_id
    assert len(provider.charges) == 1
    assert divida(session) == (1000, 300)


def test_so_cobra_pix_de_corrida_aceita_por_um_motoqueiro(session, service):
    mundo(session, method=PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="Pix"):
        service.start_pix_charge(session, "ride-1", FEE)
    ride = Ride("ride-2", "p1", 700, PaymentMethod.PIX, pin="4821")
    repo.add_ride(session, ride)
    with pytest.raises(InvalidTransition):
        service.start_pix_charge(session, "ride-2", FEE)


def test_pix_pago_abate_a_divida_lanca_no_livro_e_marca_a_corrida(session, service, provider):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_ride(session, "ride-1").pix_paid is True
    assert divida(session) == (700, 0)
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300
    assert ledger.balance(PgLedger.COMPANY) == 400
    assert ledger.balance(PgLedger.PROVIDER) == -700
    assert ledger.is_balanced() is True
    salva = repo.get_charge(session, charge.charge_id)
    assert salva.paid is True and salva.debt_state is DebtState.APPLIED


def test_aviso_repetido_nao_conta_duas_vezes(session, service, provider):
    # Review Focus 1
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    event = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, event) == "applied"
    assert service.on_provider_event(session, event) == "duplicate"
    assert divida(session) == (700, 0)
    assert PgLedger(session).balance("rider:r1") == 300


def test_aviso_novo_para_cobranca_ja_paga_tambem_e_ignorado(session, service, provider):
    # Review Focus 1
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    event = provider.mark_paid(charge.charge_id)
    service.on_provider_event(session, event)
    outro_id = {**event, "event_id": "evt-outro"}
    assert service.on_provider_event(session, outro_id) == "duplicate"
    assert PgLedger(session).balance("rider:r1") == 300


def test_tipo_de_aviso_desconhecido_da_erro(session, service):
    with pytest.raises(ValueError, match="desconhecido"):
        service.on_provider_event(session, {"event_id": "e", "type": "outro", "charge_id": "ch-1"})


def test_pix_vencido_cancela_e_libera_a_reserva(session, service):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.expire_unpaid_pix(session, "ride-1", now=129) is False
    assert service.expire_unpaid_pix(session, "ride-1", now=130) is True
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert divida(session) == (1000, 0)
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED


def test_cancelar_antes_de_pagar_libera_a_reserva(session, service):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.cancel_ride(session, "ride-1", now=20) == CancelResult(0, False)
    assert divida(session) == (1000, 0)
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED


def test_cancelar_corrida_paga_devolve_o_dinheiro_e_a_divida(session, service, provider):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.on_provider_event(session, provider.mark_paid(charge.charge_id))
    assert service.cancel_ride(session, "ride-1", now=20) == CancelResult(0, True)
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.is_balanced() is True
    assert divida(session) == (1000, 0)
    salva = repo.get_charge(session, charge.charge_id)
    assert salva.refunded is True and salva.debt_state is DebtState.RESTORED


def test_aviso_atrasado_de_corrida_cancelada_e_devolvido(session, service, provider):
    # Review Focus 1 e 2: o passageiro pagou no último segundo, mas o Pix já tinha vencido.
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.expire_unpaid_pix(session, "ride-1", now=130)
    event = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, event) == "refunded"
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.is_balanced() is True
    assert divida(session) == (1000, 0)
    assert repo.get_ride(session, "ride-1").pix_paid is False


def test_corrida_na_fila_paga_volta_para_a_busca_com_estorno(session, service, provider):
    mundo(session, busy=True)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert service.release_queued_ride(session, "ride-1", now=500) is True
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.SEARCHING
    assert ride.rider_id is None
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert provider.charges[charge.charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert divida(session) == (1000, 0)


def test_corrida_na_fila_sem_pagar_volta_para_a_busca_e_libera_a_reserva(session, service):
    mundo(session, busy=True)
    service.start_pix_charge(session, "ride-1", FEE)
    assert service.release_queued_ride(session, "ride-1", now=500) is False
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert divida(session) == (1000, 0)


def test_aviso_de_cobranca_antiga_nao_marca_a_corrida_atual_como_paga(session, service, provider):
    # Review Focus 1: a moto r1 saiu da corrida; o passageiro pagou a cobrança velha na última hora.
    mundo(session, busy=True)
    add_rider(session, user_id="r2", phone="+5575900000009", cpf="222.222.222-22", cnh="CNH0002", plate="BBB2B22")
    velha = service.start_pix_charge(session, "ride-1", FEE)
    service.release_queued_ride(session, "ride-1", now=500)
    ride = repo.get_ride(session, "ride-1")
    accept(ride, "r2", 510, rider_busy=False)
    repo.save_ride(session, ride)
    nova = service.start_pix_charge(session, "ride-1", FEE)
    assert nova.charge_id != velha.charge_id

    assert service.on_provider_event(session, provider.mark_paid(velha.charge_id)) == "refunded"
    assert repo.get_ride(session, "ride-1").pix_paid is False
    assert provider.charges[velha.charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert repo.get_current_charge_id(session, "ride-1") == nova.charge_id


def test_falha_do_provedor_no_estorno_nao_deixa_nada_pela_metade(session, provider):
    # Review Focus 4: o chamador desfaz a transação e tudo volta ao que era.
    servico = PaymentService(provider)
    mundo(session)
    charge = servico.start_pix_charge(session, "ride-1", FEE)
    servico.on_provider_event(session, provider.mark_paid(charge.charge_id))
    ruim = PaymentService(RefundFalha())
    with pytest.raises(RuntimeError, match="provedor"):
        with session.begin_nested():
            ruim.cancel_ride(session, "ride-1", now=20)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.ACCEPTED
    assert ride.pix_paid is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300
    assert divida(session) == (700, 0)
    assert repo.get_charge(session, charge.charge_id).refunded is False


def _chegada(session, ride_id="ride-1", now=100.0):
    ride = repo.get_ride(session, ride_id)
    mark_arrived(ride, now)
    repo.save_ride(session, ride)


def test_espera_na_chegada_esgotada_com_pix_pago_devolve_o_dinheiro_e_a_divida(session, service, provider):
    # Review final: sem este caso de uso o Pix pago ficava no livro quando o passageiro não aparecia.
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.on_provider_event(session, provider.mark_paid(charge.charge_id))
    _chegada(session)
    resultado = service.cancel_after_arrival_timeout(session, "ride-1", now=100 + 300)
    assert resultado == CancelResult(200, True)
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.is_balanced() is True
    assert divida(session) == (1000, 0)
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    salva = repo.get_charge(session, charge.charge_id)
    assert salva.refunded is True and salva.debt_state is DebtState.RESTORED


def test_espera_na_chegada_antes_do_prazo_nao_cancela_nada(session, service, provider):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.on_provider_event(session, provider.mark_paid(charge.charge_id))
    _chegada(session)
    with pytest.raises(InvalidTransition, match="espera"):
        service.cancel_after_arrival_timeout(session, "ride-1", now=100 + 299)
    assert repo.get_ride(session, "ride-1").state is RideState.ARRIVED
    assert provider.charges[charge.charge_id].refunded is False
    assert PgLedger(session).balance("rider:r1") == 300


def test_espera_na_chegada_esgotada_em_dinheiro_so_cancela_com_compensacao(session, service):
    mundo(session, method=PaymentMethod.CASH)
    _chegada(session)
    assert service.cancel_after_arrival_timeout(session, "ride-1", now=100 + 300) == CancelResult(200, False)
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert divida(session) == (1000, 0)
