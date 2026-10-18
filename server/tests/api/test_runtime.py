import dataclasses

import psycopg.errors
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.config_store import save_config
from app.db.models import UserRow
from app.domain.config import RideConfig
from app.runtime import Runtime, build_runtime
from tests.api.conftest import Gravador


def _usuario(unit, user_id="p1"):
    repo.add_user(unit.session, user_id=user_id, phone="+5575900000001", name="Ana", role="passenger")
    unit.events.add(user_id, "ola", {"a": 1})


def test_depois_do_commit_publica_os_avisos_da_unidade(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)
    runtime.run(lambda unit: _usuario(unit))
    assert gravador.types == ["ola"]
    assert gravador.messages[0]["data"] == {"a": 1}
    assert gravador.messages[0]["at"] == runtime.clock()
    assert session.get(UserRow, "p1") is not None


def test_o_commit_vem_antes_da_publicacao(runtime, session):
    ordem: list[str] = []

    class SessaoQueAnota(Session):
        def commit(self):
            ordem.append("commit")
            super().commit()

    class HubQueAnota:
        def publish_events(self, events, now):
            ordem.append("publica")

    sessao = SessaoQueAnota(bind=session.get_bind(), join_transaction_mode="create_savepoint", expire_on_commit=False)
    runtime.session_factory = lambda: sessao
    runtime.hub = HubQueAnota()
    runtime.run(lambda unit: unit.events.add("p1", "ola"))
    sessao.close()
    assert ordem == ["commit", "publica"]


def test_erro_no_meio_desfaz_o_banco_e_nao_publica_nada(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)

    def trabalho(unit):
        _usuario(unit)
        raise RuntimeError("quebrou")

    with pytest.raises(RuntimeError):
        runtime.run(trabalho)
    assert gravador.messages == []
    assert session.get(UserRow, "p1") is None


def _impasse():
    return OperationalError("UPDATE ...", {}, psycopg.errors.DeadlockDetected())


def test_impasse_no_banco_repete_a_unidade_com_avisos_novos(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)
    tentativas = []

    def trabalho(unit):
        tentativas.append(unit.events)
        unit.events.add("p1", f"tentativa-{len(tentativas)}")
        if len(tentativas) == 1:
            raise _impasse()
        return "ok"

    assert runtime.run(trabalho) == "ok"
    assert len(tentativas) == 2 and tentativas[0] is not tentativas[1]
    assert gravador.types == ["tentativa-2"]          # o aviso da tentativa desfeita não sai


def test_impasse_que_nao_passa_depois_das_repeticoes_estoura(runtime):
    chamadas = []

    def trabalho(unit):
        chamadas.append(1)
        raise _impasse()

    with pytest.raises(OperationalError):
        runtime.run(trabalho, retries=2)
    assert len(chamadas) == 3


def test_outro_erro_do_banco_nao_e_repetido(runtime):
    chamadas = []

    def trabalho(unit):
        chamadas.append(1)
        raise OperationalError("SELECT 1", {}, psycopg.errors.AdminShutdown())

    with pytest.raises(OperationalError):
        runtime.run(trabalho)
    assert len(chamadas) == 1


def test_falha_ao_publicar_nao_derruba_o_pedido(runtime, session):
    class HubQuebrado:
        def publish_events(self, events, now):
            raise RuntimeError("hub caiu")

    runtime.hub = HubQuebrado()
    runtime.run(lambda unit: _usuario(unit))
    assert session.get(UserRow, "p1") is not None


def test_todos_os_servicos_da_unidade_dividem_o_mesmo_coletor(runtime):
    def trabalho(unit):
        return {
            unit.events, unit.riders.events, unit.payments.events, unit.dispatch.events, unit.trips.events,
            unit.requests.events, unit.sweeps.events,
        }

    assert len(runtime.run(trabalho)) == 1
    primeiro, segundo = runtime.run(lambda u: u.events), runtime.run(lambda u: u.events)
    assert primeiro is not segundo        # cada unidade de trabalho tem o seu; nunca um coletor global


def test_a_unidade_usa_o_relogio_do_servidor_e_a_configuracao_guardada(runtime, session, clock):
    assert runtime.run(lambda u: u.now) == clock.now
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 120
    save_config(session, "rides", dataclasses.replace(RideConfig(), pix_window_s=90))
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 120      # ainda no cache de 30 s
    clock.advance(31)
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 90
    assert runtime.run(lambda u: u.payments.ride_cfg.pix_window_s) == 90


def test_modo_de_producao_recusa_subir_com_adaptadores_falsos(settings):
    with pytest.raises(RuntimeError, match="plano 7"):
        build_runtime(dataclasses.replace(settings, mode="production"))


def test_sem_o_segredo_do_aviso_do_provedor_o_servidor_nao_sobe(settings):
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        build_runtime(dataclasses.replace(settings, mode="dev", webhook_secret=None))


def test_modo_dev_monta_tudo_com_redis_de_verdade(settings, redis_test_url, redis_client):
    runtime = build_runtime(
        dataclasses.replace(settings, mode="dev", redis_url=redis_test_url, webhook_secret="segredo-de-teste")
    )
    assert isinstance(runtime, Runtime) and runtime.mode == "dev"
    runtime.check()                                   # banco e Redis respondem
    assert runtime.positions.get("ninguem") is None
    assert runtime.pix_health.is_down(1.0) is False


def test_saude_acusa_quando_o_banco_nao_responde(runtime):
    class SessaoRuim:
        def __enter__(self):
            raise RuntimeError("sem banco")

        def __exit__(self, *args):
            return False

    runtime.session_factory = lambda: SessaoRuim()
    with pytest.raises(RuntimeError):
        runtime.check()
