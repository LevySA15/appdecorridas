from simulator.behavior import Profile
from simulator.report import brl, build_report, find_problems, span
from simulator.model import Outcome, SimConfig
from simulator.stats import RideRecord, Stats

AUDIT_OK = {
    "ledger_balanced": True, "reconcile_diff": {}, "rides_by_state": {"completed": 1}, "open_rides": [],
    "double_booked_riders": [],
}


def corrida(ride_id="ride-1", outcome="completed", method="pix", price=700, **times):
    base = dict(requested_at=0.0, accepted_at=5.0, arrived_at=65.0, started_at=75.0, ended_at=195.0)
    base.update(times)
    return RideRecord(ride_id, 1, method, price, "Preço normal.", outcome=outcome, **base)


def rodada(rides=(), audit=None, stats=None) -> Outcome:
    stats = stats or Stats()
    for ride in rides:
        stats.rides[ride.ride_id] = ride
    cfg = SimConfig(url="http://x", admin_phone="75 99999-0000", riders=2, passengers=3, profile=Profile())
    return Outcome(cfg, stats, AUDIT_OK if audit is None else audit, 200.0, 2)


def test_formatos_de_dinheiro_e_de_tempo():
    assert brl(550) == "R$ 5,50" and brl(5000) == "R$ 50,00"
    assert span(None) == "–" and span(42) == "42 s" and span(75) == "1 min 15 s" and span(120) == "2 min 00 s"


def test_rodada_limpa_passa_e_conta_as_corridas_e_o_dinheiro():
    relatorio = build_report(rodada([corrida(), corrida("ride-2", method="cash", price=550)]))
    assert relatorio.passed and "**Tudo certo.**" in relatorio.text
    assert "concluídas: 2" in relatorio.text and "Pix: 1 corridas, R$ 7,00" in relatorio.text
    assert "dinheiro: 1 corridas, R$ 5,50" in relatorio.text
    assert "mediana 1 min 00 s" in relatorio.text            # do aceite (5 s) até a moto chegar (65 s)


def test_resposta_inesperada_do_servidor_reprova_e_aparece_na_lista():
    stats = Stats()
    stats.flag("POST /v1/rider/offers/{ride_id}/accept: 500")
    relatorio = build_report(rodada([corrida()], stats=stats))
    assert not relatorio.passed and "1 resposta(s) inesperada(s)" in relatorio.problems[0]
    assert "- POST /v1/rider/offers/{ride_id}/accept: 500" in relatorio.text


def test_conferencia_do_servidor_reprova_livro_aberto_diferenca_e_moto_em_duas_corridas():
    audit = {
        "ledger_balanced": False, "reconcile_diff": {"charge:ch-1": 700}, "rides_by_state": {},
        "open_rides": [{"ride_id": "ride-1", "state": "accepted"}, {"ride_id": "de-outra-rodada", "state": "searching"}],
        "double_booked_riders": ["r1"],
    }
    problemas = find_problems(rodada([corrida()], audit=audit), [])
    texto = " ".join(problemas)
    assert "NÃO fecha" in texto and "charge:ch-1" in texto and "r1" in texto
    assert "1 corrida(s) ficaram abertas" in texto            # só as desta rodada contam, não "de-outra-rodada"


def test_sem_resposta_da_conferencia_tambem_e_problema():
    assert "conferência final" in find_problems(rodada([corrida()], audit={}), [])[0]


def test_corrida_sem_desfecho_e_aviso_perdido_reprovam_e_o_registro_do_servidor_tambem():
    perdida = corrida("ride-2", outcome="unknown")
    sem_aviso = corrida("ride-3")
    sem_aviso.missing_events = ["trip_completed"]
    problemas = find_problems(rodada([perdida, sem_aviso]), ["Traceback (most recent call last):"])
    texto = " ".join(problemas)
    assert "sumiram do estado" in texto and "1 aviso(s) em tempo real" in texto and "No registro do servidor" in texto


def test_rotas_aparecem_com_erros_e_tempos():
    stats = Stats()
    stats.record_call("GET", "/v1/passenger/state", 200, 0.010)
    stats.record_call("GET", "/v1/passenger/state", 200, 0.030)
    stats.record_call("POST", "/v1/passenger/rides", 409, 0.050)
    texto = build_report(rodada([corrida()], stats=stats)).text
    assert "| GET /v1/passenger/state | 2 | 0 | 10 ms | 30 ms | 30 ms |" in texto
    assert "| POST /v1/passenger/rides | 1 | 1 | 50 ms | 50 ms | 50 ms |" in texto


def test_suspeita_de_localizacao_falsa_aparece_no_relatorio_sem_reprovar():
    stats = Stats()
    stats.events["mock_location_suspected"] = 2
    relatorio = build_report(rodada([corrida()], stats=stats))
    assert relatorio.passed and "localização falsa" in relatorio.text and "avisou ao administrador: 2" in relatorio.text
    assert "localização falsa" not in build_report(rodada([corrida()])).text
