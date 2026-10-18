import httpx2 as httpx
from sqlalchemy import text

from app.cli import create_admin
from app.db.config_store import load_app_config
from simulator.sandbox import ADMIN_PHONE, Sandbox, seed_database


def test_semente_libera_os_limites_de_login_e_cria_o_administrador(session):
    seed_database(session, fast=False)
    cfg = load_app_config(session)
    assert cfg.auth.otp_requests_per_ip_hour >= 100_000 and cfg.auth.otp_requests_per_hour >= 1000
    assert cfg.rides.pix_window_s == 120            # o resto continua como o servidor de verdade
    assert create_admin(session, ADMIN_PHONE, "qualquer") == create_admin(session, ADMIN_PHONE, "outro")


def test_semente_rapida_encurta_os_prazos_do_servidor(session):
    seed_database(session, fast=True)
    cfg = load_app_config(session)
    assert cfg.rides.pix_window_s < 120 and cfg.rides.cash_pay_wait_s < 300 and cfg.rides.search_give_up_s < 120
    assert cfg.dispatch.offer_timeout_s < 15 and cfg.safety.stopped_after_s < 180


def test_servidor_descartavel_sobe_responde_e_some_sem_deixar_rastro(settings):
    with Sandbox(redis_db=13) as box:
        cliente = httpx.Client(base_url=box.url, timeout=5)
        assert cliente.get("/health").json() == {"status": "ok"}
        assert cliente.get("/v1/dev/audit").json()["ledger_balanced"] is True
        schema = box.schema
        processo = box.process
        assert box.problems() == [] and box.retries() == 0
    assert processo.poll() is not None
    import sqlalchemy

    engine = sqlalchemy.create_engine(settings.database_url)
    with engine.connect() as conn:
        restou = conn.execute(text("select count(*) from information_schema.schemata where schema_name = :s"), {"s": schema}).scalar()
    engine.dispose()
    assert restou == 0


def test_erro_dentro_do_bloco_tambem_apaga_o_esquema(settings):
    import pytest
    import sqlalchemy

    with pytest.raises(RuntimeError, match="boom"):
        with Sandbox(redis_db=13) as box:
            schema = box.schema
            raise RuntimeError("boom")
    engine = sqlalchemy.create_engine(settings.database_url)
    with engine.connect() as conn:
        restou = conn.execute(text("select count(*) from information_schema.schemata where schema_name = :s"), {"s": schema}).scalar()
    engine.dispose()
    assert restou == 0
