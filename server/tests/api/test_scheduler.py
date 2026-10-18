import asyncio
import datetime as dt
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.db.models import RiderProfileRow
from app.domain.clock import local_date
from app.scheduler import POSITION_MAX_AGE_S, Scheduler, prune_positions, run_daily_jobs, sweep_once
from app.services.payments import PaymentService
from app.services.riders import RiderService
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


def pix_aceito(client, runtime, session, clock):
    pax = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    online_rider(session, runtime, clock, 1)
    rider = login(client, runtime, rider_phone(1), "rider")
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    pedido = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "pix"}, headers=pax.headers
    ).json()
    client.post(f"/v1/rider/offers/{pedido['ride_id']}/accept", headers=rider.headers)
    return pax, rider, pedido


# --- varredura ------------------------------------------------------------------------------------


def test_varredura_cancela_pix_vencido_e_publica_os_avisos_depois_do_commit(client, runtime, session, clock, listen):
    pax, rider, pedido = pix_aceito(client, runtime, session, clock)
    avisos_pax, avisos_rider = listen(pax.user_id), listen(rider.user_id)
    assert sweep_once(runtime).pix_expired == 0
    clock.advance(121)
    relatorio = sweep_once(runtime)
    assert relatorio.pix_expired == 1 and relatorio.errors == []
    assert avisos_pax.types == ["ride_cancelled"] and avisos_rider.types == ["ride_cancelled"]
    assert avisos_pax.messages[0]["data"] == {"ride_id": pedido["ride_id"], "reason": "pix_expired"}
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None


def test_erro_numa_corrida_vai_para_o_registro_e_o_servidor_segue(
    client, runtime, session, clock, monkeypatch, caplog
):
    pix_aceito(client, runtime, session, clock)
    clock.advance(121)

    def quebra(self, *args, **kwargs):
        raise RuntimeError("provedor caiu")

    monkeypatch.setattr(PaymentService, "expire_unpaid_pix", quebra)
    with caplog.at_level(logging.ERROR, logger="app.scheduler"):
        relatorio = sweep_once(runtime)
    assert len(relatorio.errors) == 1 and relatorio.pix_expired == 0
    assert any("provedor caiu" in r.getMessage() for r in caplog.records)


# --- tarefa diária de documentos --------------------------------------------------------------------


def rider_com_cnh_vencida(session, runtime, clock):
    rider_id = online_rider(session, runtime, clock, 1)
    session.get(RiderProfileRow, rider_id).cnh_expires_on = local_date(clock.now) - dt.timedelta(days=1)
    session.commit()        # a unidade que falha desfaz o que não foi gravado; o cenário precisa estar gravado
    return rider_id


def test_documento_vencido_bloqueia_uma_vez_por_dia(runtime, session, clock, listen):
    rider_id = rider_com_cnh_vencida(session, runtime, clock)
    avisos = listen(rider_id)
    assert run_daily_jobs(runtime) == 1
    perfil = session.get(RiderProfileRow, rider_id)
    assert (perfil.status, perfil.online, perfil.rejected_reason) == ("blocked", False, "documento vencido")
    assert avisos.types == ["documents_expired"] and runtime.positions.get(rider_id) is None
    assert run_daily_jobs(runtime) is None                       # já rodou hoje
    clock.advance(86_400)
    assert run_daily_jobs(runtime) == 0                          # outro dia, nada novo para bloquear


def test_se_a_tarefa_diaria_falhar_ela_tenta_de_novo_na_proxima_volta(runtime, session, clock, monkeypatch):
    rider_id = rider_com_cnh_vencida(session, runtime, clock)
    original = RiderService.block_expired_documents
    chamadas = []

    def falha_na_primeira(self, *args, **kwargs):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("banco caiu")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RiderService, "block_expired_documents", falha_na_primeira)
    with pytest.raises(RuntimeError):
        run_daily_jobs(runtime)
    assert run_daily_jobs(runtime) == 1
    assert session.get(RiderProfileRow, rider_id).status == "blocked"


# --- limpeza das posições ---------------------------------------------------------------------------


def test_limpeza_tira_do_mapa_quem_some_sem_avisar(runtime, clock):
    runtime.positions.update("sumiu", pt(0, 0), clock.now - POSITION_MAX_AGE_S - 1)
    runtime.positions.update("firme", pt(10, 0), clock.now - 30)
    assert prune_positions(runtime) == 1
    assert runtime.positions.get("sumiu") is None and runtime.positions.get("firme") is not None


# --- o agendador ----------------------------------------------------------------------------------------


def test_cada_volta_varre_e_a_manutencao_so_roda_de_minuto_em_minuto(runtime, clock, monkeypatch):
    chamadas = []
    monkeypatch.setattr("app.scheduler.sweep_once", lambda rt: chamadas.append("varre"))
    monkeypatch.setattr("app.scheduler.run_daily_jobs", lambda rt: chamadas.append("diaria"))
    monkeypatch.setattr("app.scheduler.prune_positions", lambda rt: chamadas.append("limpa"))
    agendador = Scheduler(runtime)
    agendador.tick()
    clock.advance(3)
    agendador.tick()
    clock.advance(58)
    agendador.tick()
    assert chamadas == ["varre", "diaria", "limpa", "varre", "varre", "diaria", "limpa"]


def test_uma_volta_que_estoura_nao_derruba_o_agendador(runtime, caplog):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)
            if len(voltas) == 1:
                raise RuntimeError("banco caiu")

    async def main():
        tarefa = asyncio.create_task(Agendador(runtime, sweep_interval_s=0.01).run())
        while len(voltas) < 3:
            await asyncio.sleep(0.01)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa

    with caplog.at_level(logging.ERROR, logger="app.scheduler"):
        asyncio.run(main())
    assert len(voltas) >= 3 and any("banco caiu" in r.getMessage() for r in caplog.records)


def test_o_agendador_liga_com_o_servidor_e_para_junto(runtime):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)

    with TestClient(create_app(runtime, run_background=True, scheduler=Agendador(runtime, sweep_interval_s=0.01))):
        for _ in range(200):
            if len(voltas) >= 3:
                break
            time.sleep(0.01)
        assert len(voltas) >= 3
    parou_em = len(voltas)
    time.sleep(0.1)
    assert len(voltas) == parou_em


def test_sem_run_background_nao_tem_agendador(runtime):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)

    with TestClient(create_app(runtime, scheduler=Agendador(runtime, sweep_interval_s=0.01))):
        time.sleep(0.1)
    assert voltas == []
