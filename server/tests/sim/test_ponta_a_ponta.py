"""A simulação de verdade contra um servidor de verdade: uma corrida inteira, no Pix e em dinheiro."""
import asyncio
import dataclasses

import pytest

from simulator.behavior import Profile, fast_timings, preset
from simulator.report import build_report
from simulator.runner import SimConfig, simulate
from simulator.sandbox import ADMIN_PHONE


def perfil_rapido(pix_share: float) -> Profile:
    """Gente calma, prazos curtos, cidade minúscula e motos a 115 km/h: uma corrida inteira em cerca de meio minuto."""
    return dataclasses.replace(
        fast_timings(preset("calmo")), pix_share=pix_share, accept=1.0, decline=0.0, pace=0.1, city_scale=0.1,
        mean_gap_s=10.0, position_every_s=1.0, poll_every_s=1.0, tick_s=0.25,
    )


@pytest.mark.parametrize("metodo", ["pix", "cash"])
def test_uma_corrida_inteira_sem_nenhuma_resposta_inesperada(box, metodo):
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=7,
        profile=perfil_rapido(1.0 if metodo == "pix" else 0.0), max_rides=1, drain_s=90,
    )
    outcome = asyncio.run(simulate(cfg))
    relatorio = build_report(outcome, box.problems(), box.retries())
    assert relatorio.passed, relatorio.text
    [corrida] = outcome.stats.rides.values()
    assert corrida.outcome == "completed" and corrida.method == metodo and corrida.missing_events == []
    assert outcome.audit["rides_by_state"] == {"completed": 1}
    if metodo == "pix":
        assert outcome.stats.events["pix_confirmed"] == 1
    else:
        assert outcome.stats.notes["dinheiro confirmado na mão"] == 1


@pytest.mark.slow
def test_resposta_tardia_a_oferta_vencida_nao_assusta_o_servidor(box):
    """O motoqueiro só responde depois de a oferta vencer e o passageiro desiste: o servidor responde 409 `offer_gone`."""
    perfil = dataclasses.replace(
        perfil_rapido(0.0), accept=0.0, decline=0.0, late=1.0, cancel_while_searching=1.0
    )
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=3, profile=perfil, max_rides=1,
        drain_s=60,
    )
    outcome = asyncio.run(simulate(cfg))
    relatorio = build_report(outcome, box.problems(), box.retries())
    assert relatorio.passed, relatorio.text
    [corrida] = outcome.stats.rides.values()
    assert corrida.outcome == "cancelled"
    assert outcome.stats.notes["oferta respondida tarde"] == 1 and outcome.stats.notes["passageiro cancelou"] == 1
    assert outcome.stats.calls[("POST", "/v1/rider/offers/{ride_id}/accept", 409)] == 1       # esperado, não alarme


@pytest.mark.slow
def test_tapas_duplos_codigo_errado_e_sos_terminam_bem(box):
    """O que o perfil "bagunça" faz, ligado de propósito numa corrida só: o servidor tem de aguentar e fechar as contas."""
    perfil = dataclasses.replace(
        perfil_rapido(0.0), double_request=1.0, double_tap=1.0, wrong_pin=1.0, spontaneous_sos=1.0,
        emergency_contact=1.0,
    )
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=5, profile=perfil, max_rides=1,
        drain_s=90,
    )
    outcome = asyncio.run(simulate(cfg))
    relatorio = build_report(outcome, box.problems(), box.retries())
    assert relatorio.passed, relatorio.text
    [corrida] = outcome.stats.rides.values()
    assert corrida.outcome == "completed"
    notas = outcome.stats.notes
    assert notas["toque duplo em pedir"] == 1 and notas["toque duplo em aceitar"] == 1
    assert notas["código errado digitado"] == 1 and notas["SOS apertado"] == 1
    assert outcome.stats.events["sos_sent"] == 1
    assert outcome.stats.events["sos"] == 1                    # o administrador de mentira também recebeu o aviso
    assert notas["alerta de segurança resolvido pelo administrador (sos)"] == 1
    assert outcome.audit["rides_by_state"] == {"completed": 1}


def perfil_de_taxa(**mudancas) -> Profile:
    """O passageiro cancela 16 s depois de a moto aceitar (a janela grátis do servidor rápido é de 15 s), com a moto
    ainda longe: taxa de cancelamento tardio de R$ 3,00."""
    return dataclasses.replace(
        perfil_rapido(0.0), speed_mps=1.0, speedup=1.0, cancel_after_accept=1.0, cancel_accept_s=(160.0, 165.0),
        **mudancas,
    )


def rodar_taxa(box, perfil, seed=11):
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=seed, profile=perfil,
        max_rides=1, drain_s=120,
    )
    outcome = asyncio.run(simulate(cfg))
    return outcome, build_report(outcome, box.problems(), box.retries())


def test_rodada_com_cancelamento_tardio_cobra_a_taxa_e_o_livro_fecha(box):
    outcome, relatorio = rodar_taxa(box, perfil_de_taxa(pay_fee=1.0, appeal_fee=0.0, topup=0.0))
    assert relatorio.passed, relatorio.text
    fees = outcome.stats.fees
    assert fees["cobradas"] == 1 and fees["pendentes"] == 1 and fees["pagas_depois"] == 1
    assert 300 <= fees["centavos"] <= 500
    assert outcome.audit["balance_matches_ledger"] is True and outcome.audit["inconsistent_fees"] == []
    assert outcome.stats.events["fee_paid"] == 1
    assert "Cobradas: 1" in relatorio.text


@pytest.mark.slow
def test_passageiro_que_escolhe_nao_pagar_a_taxa_fica_bloqueado_e_a_rodada_termina(box):
    outcome, relatorio = rodar_taxa(box, perfil_de_taxa(pay_fee=0.0, appeal_fee=0.0, topup=0.0))
    assert relatorio.passed, relatorio.text
    assert outcome.stats.fees["cobradas"] == 1 and outcome.stats.fees["pagas_depois"] == 0
    assert outcome.stats.notes["taxa pendente não paga (por escolha)"] == 1


@pytest.mark.slow
def test_recurso_da_taxa_e_decidido_pelo_administrador_de_mentira(box):
    outcome, relatorio = rodar_taxa(box, perfil_de_taxa(pay_fee=0.0, appeal_fee=1.0, topup=0.0))
    assert relatorio.passed, relatorio.text
    fees = outcome.stats.fees
    assert fees["recursos_pedidos"] == 1 and fees["recursos_aceitos"] + fees["recursos_recusados"] == 1
    assert outcome.audit["balance_matches_ledger"] is True


@pytest.mark.slow
def test_recarga_de_saldo_paga_a_taxa_sem_pendencia(box):
    perfil = perfil_de_taxa(pay_fee=1.0, appeal_fee=0.0, topup=1.0)
    outcome, relatorio = rodar_taxa(box, perfil)
    assert relatorio.passed, relatorio.text
    fees = outcome.stats.fees
    assert fees["recargas"] == 1 and fees["cobradas"] == 1 and fees["do_saldo"] >= 300 and fees["pendentes"] == 0, relatorio.text
    assert outcome.audit["balance_matches_ledger"] is True


@pytest.mark.slow
def test_motoqueiro_que_perde_o_sinal_gera_o_alerta_e_o_passageiro_responde(box):
    """A moto anda devagar e fica 150 s sem mandar posição no meio da viagem: o servidor rápido alerta aos 40 s."""
    perfil = dataclasses.replace(
        perfil_rapido(0.0), speed_mps=1.0, speedup=1.0, lose_signal=1.0, lose_signal_s=150.0, emergency_contact=1.0
    )
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=11, profile=perfil, max_rides=1,
        drain_s=120,
    )
    outcome = asyncio.run(simulate(cfg))
    relatorio = build_report(outcome, box.problems(), box.retries(), box.error_details())
    assert relatorio.passed, relatorio.text
    [corrida] = outcome.stats.rides.values()
    assert corrida.outcome == "completed"
    notas = outcome.stats.notes
    assert notas["moto ficou sem sinal de propósito"] == 1
    assert outcome.stats.events["safety_check"] >= 1 and outcome.stats.events["safety_alert"] >= 1
    assert notas["respondeu \"está tudo bem\""] >= 1


def perfil_de_divida(**mudancas) -> Profile:
    """Dinheiro vivo, o passageiro não paga o QR e o motoqueiro confirma o dinheiro na mão: a taxa vira dívida dele."""
    return dataclasses.replace(perfil_rapido(0.0), pay_qr=0.0, cash_by_hand=1.0, **mudancas)


def rodar_divida(box, perfil, rides=2, seed=11):
    cfg = SimConfig(
        url=box.url, admin_phone=ADMIN_PHONE, riders=1, passengers=1, minutes=3, seed=seed, profile=perfil,
        max_rides=rides, drain_s=150,
    )
    outcome = asyncio.run(simulate(cfg))
    return outcome, build_report(outcome, box.problems(), box.retries(), box.error_details())


@pytest.mark.slow
def test_motoqueiro_que_deve_a_taxa_e_bloqueado_paga_e_volta_a_trabalhar(box):
    outcome, relatorio = rodar_divida(box, perfil_de_divida(pay_debt=1.0))
    assert relatorio.passed, relatorio.text
    assert sorted(r.outcome for r in outcome.stats.rides.values()) == ["completed", "completed"]
    assert outcome.stats.notes["dívida da taxa paga"] >= 1
    assert outcome.stats.events["debt_required"] >= 1 and outcome.stats.events["debt_paid"] >= 1
    assert outcome.audit["ledger_balanced"] is True and outcome.audit["reconcile_diff"] == {}


@pytest.mark.slow
def test_motoqueiro_que_escolhe_nao_pagar_fica_bloqueado_e_a_rodada_termina(box):
    outcome, relatorio = rodar_divida(box, perfil_de_divida(pay_debt=0.0))
    assert relatorio.passed, relatorio.text
    resultados = sorted(r.outcome for r in outcome.stats.rides.values())
    assert resultados.count("completed") == 1 and "completed" in resultados and len(resultados) == 2
    assert outcome.stats.notes["dívida da taxa não paga (por escolha)"] == 1
    assert outcome.stats.notes["dívida da taxa paga"] == 0
