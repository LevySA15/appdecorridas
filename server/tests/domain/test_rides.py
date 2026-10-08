import pytest

from app.domain.config import RideConfig
from app.domain.rides import (
    InvalidTransition,
    PassengerAccount,
    Ride,
    RideState,
    accept,
    arrival_wait_expired,
    can_request,
    cancel,
    cancel_after_arrival_timeout,
    cancel_unpaid_pix,
    complete,
    confirm_end_payment,
    confirm_helmet,
    confirm_pix_paid,
    mark_arrived,
    mark_no_rider,
    pix_window_expired,
    promote_from_queue,
    queue_wait_expired,
    release_from_queue,
    report_non_payment,
    settle_passenger_debt,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod

CFG = RideConfig()


def make_ride(method: PaymentMethod = PaymentMethod.PIX) -> Ride:
    return Ride(ride_id="ride-1", passenger_id="p1", price_cents=700, payment_method=method, pin="4821")


def accepted_ride(method: PaymentMethod = PaymentMethod.PIX, now: float = 10.0) -> Ride:
    ride = make_ride(method)
    start_search(ride, 0)
    accept(ride, "rider-1", now, rider_busy=False)
    return ride


def arrived_ride(method: PaymentMethod = PaymentMethod.PIX) -> Ride:
    ride = accepted_ride(method)
    mark_arrived(ride, 100)
    return ride


def test_corrida_pix_do_pedido_ao_fim():
    ride = make_ride()
    start_search(ride, now=0)
    assert ride.state is RideState.SEARCHING
    accept(ride, "rider-1", now=10, rider_busy=False)
    assert ride.state is RideState.ACCEPTED
    assert ride.rider_id == "rider-1"
    assert ride.pix_charge_created_at == 10
    confirm_pix_paid(ride)
    mark_arrived(ride, now=100)
    confirm_helmet(ride)
    start_ride(ride, pin="4821")
    assert ride.state is RideState.IN_PROGRESS
    complete(ride)
    assert ride.state is RideState.COMPLETED


def test_corrida_em_dinheiro_nao_cria_cobranca_pix():
    ride = arrived_ride(PaymentMethod.CASH)
    assert ride.pix_charge_created_at is None
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    confirm_end_payment(ride)
    assert ride.end_payment_confirmed is True


def test_nao_inicia_sem_confirmar_o_capacete():
    ride = arrived_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="capacete"):
        start_ride(ride, "4821")


def test_nao_inicia_com_codigo_errado():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    with pytest.raises(ValueError, match="código"):
        start_ride(ride, "0000")
    assert ride.state is RideState.ARRIVED


def test_nao_inicia_corrida_pix_sem_pagamento():
    ride = arrived_ride(PaymentMethod.PIX)
    confirm_helmet(ride)
    with pytest.raises(InvalidTransition, match="Pix"):
        start_ride(ride, "4821")


def test_nao_pula_etapas():
    ride = accepted_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition):
        start_ride(ride, "4821")
    with pytest.raises(InvalidTransition):
        complete(ride)
    with pytest.raises(InvalidTransition):
        confirm_helmet(ride)


def test_confirmar_pix_em_corrida_de_dinheiro_e_recusado():
    ride = accepted_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition):
        confirm_pix_paid(ride)


def test_corrida_na_fila_espera_e_depois_vira_a_caminho():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert ride.state is RideState.QUEUED
    assert ride.queued_since == 10
    assert ride.pix_charge_created_at == 10
    promote_from_queue(ride, now=200)
    assert ride.state is RideState.ACCEPTED
    assert ride.en_route_since == 200


def test_fila_vence_depois_de_480_segundos():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert queue_wait_expired(ride, 10 + 479, CFG) is False
    assert queue_wait_expired(ride, 10 + 480, CFG) is True


def test_fila_vencida_volta_para_a_busca_sem_estorno_se_nao_pagou():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert release_from_queue(ride, now=500) is False
    assert ride.state is RideState.SEARCHING
    assert ride.rider_id is None
    assert ride.pix_charge_created_at is None
    assert ride.searching_since == 500


def test_fila_vencida_com_pix_pago_pede_estorno():
    # Review Focus 5: o passageiro ja pagou o motoqueiro A; ao trocar de moto o dinheiro tem que voltar.
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    confirm_pix_paid(ride)
    assert release_from_queue(ride, now=500) is True
    assert ride.pix_paid is False
    assert ride.state is RideState.SEARCHING


def test_janela_de_120_segundos_para_pagar_o_pix():
    ride = accepted_ride(PaymentMethod.PIX, now=10)
    assert pix_window_expired(ride, 10 + 119, CFG) is False
    assert pix_window_expired(ride, 10 + 120, CFG) is True
    confirm_pix_paid(ride)
    assert pix_window_expired(ride, 10 + 500, CFG) is False


def test_janela_do_pix_nao_vale_para_dinheiro():
    ride = accepted_ride(PaymentMethod.CASH)
    assert pix_window_expired(ride, 10_000, CFG) is False


def test_cancelar_por_pix_nao_pago():
    ride = accepted_ride(PaymentMethod.PIX)
    cancel_unpaid_pix(ride)
    assert ride.state is RideState.CANCELLED


def test_cancelar_durante_a_procura_e_gratis():
    ride = make_ride()
    start_search(ride, 0)
    assert cancel(ride, now=5, cfg=CFG) == 0
    assert ride.state is RideState.CANCELLED


def test_cancelar_no_limite_de_60_segundos_ainda_e_gratis():
    # Review Focus 3
    ride = accepted_ride(now=10)
    assert cancel(ride, now=70, cfg=CFG) == 0


def test_cancelar_depois_de_60_segundos_paga_compensacao():
    ride = accepted_ride(now=10)
    assert cancel(ride, now=71, cfg=CFG) == 200
    assert ride.state is RideState.CANCELLED


def test_cancelar_na_fila_e_sempre_gratis():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert cancel(ride, now=10_000, cfg=CFG) == 0


def test_nao_cancela_corrida_em_andamento():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    with pytest.raises(InvalidTransition):
        cancel(ride, now=500, cfg=CFG)


def test_espera_maxima_na_chegada():
    ride = arrived_ride(PaymentMethod.CASH)  # chegou em t=100
    assert arrival_wait_expired(ride, 399, CFG) is False
    assert arrival_wait_expired(ride, 400, CFG) is True
    with pytest.raises(InvalidTransition):
        cancel_after_arrival_timeout(ride, 399, CFG)
    assert cancel_after_arrival_timeout(ride, 400, CFG) == 200
    assert ride.state is RideState.CANCELLED


def test_desiste_da_procura_em_120_segundos():
    ride = make_ride()
    start_search(ride, 0)
    with pytest.raises(InvalidTransition):
        mark_no_rider(ride, 119, CFG)
    mark_no_rider(ride, 120, CFG)
    assert ride.state is RideState.NO_RIDER


def test_passageiro_que_sai_sem_pagar_fica_bloqueado_ate_pagar():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    acc = PassengerAccount("p1")
    assert can_request(acc) is True
    report_non_payment(ride, acc)
    assert acc.unpaid_cents == 700
    assert can_request(acc) is False
    settle_passenger_debt(acc, 700)
    assert can_request(acc) is True


def test_nao_da_para_denunciar_calote_de_corrida_ja_paga():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    confirm_end_payment(ride)
    with pytest.raises(InvalidTransition):
        report_non_payment(ride, PassengerAccount("p1"))


def test_pagar_mais_que_a_divida_do_passageiro_e_recusado():
    with pytest.raises(ValueError):
        settle_passenger_debt(PassengerAccount("p1", unpaid_cents=100), 200)
