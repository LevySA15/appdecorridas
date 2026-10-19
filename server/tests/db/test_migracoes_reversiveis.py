"""Cada migração nova precisa desfazer e refazer sem erro (num esquema temporário só deste teste)."""
import uuid

from alembic import command
from sqlalchemy import create_engine, text

from tests.conftest import _alembic_config


def test_migracoes_do_0002_ao_topo_desfazem_e_refazem(settings):
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema},public"})
    config = _alembic_config()
    try:
        for passo, destino in ((command.upgrade, "head"), (command.downgrade, "0002"), (command.upgrade, "head")):
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                config.attributes["schema"] = schema
                passo(config, destino)
        with engine.connect() as conn:
            assert conn.execute(text("select to_regclass(:name)"), {"name": f'"{schema}".safety_alerts'}).scalar()
            assert conn.execute(text("select to_regclass(:name)"), {"name": f'"{schema}".cancel_fees'}).scalar()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
