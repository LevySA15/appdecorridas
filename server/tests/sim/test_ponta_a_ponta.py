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
