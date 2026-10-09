"""Fixtures de banco e Redis. Cada execução usa um esquema temporário próprio no PostgreSQL de
desenvolvimento (nunca o `public`) e o banco 15 do Redis."""
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
import redis
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.settings import load_settings

SERVER_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def db_engine(settings):
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.database_url, connect_args={"options": f"-csearch_path={schema},public"}
    )
    cfg = _alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        cfg.attributes["schema"] = schema
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        # Trava de segurança: se as tabelas não estão no esquema temporário, os testes cairiam
        # nas tabelas reais do `public` pelo search_path.
        if conn.execute(text("select to_regclass(:name)"), {"name": f'"{schema}".users'}).scalar() is None:
            raise RuntimeError(f"a migração não criou as tabelas no esquema temporário {schema}")
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture()
def session(db_engine):
    """Sessão de um teste. Os `commit` internos viram pontos de salvamento e tudo é desfeito no fim."""
    connection = db_engine.connect()
    outer = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        connection.close()


@pytest.fixture(scope="session")
def redis_test_url(settings):
    """URL do Redis de testes, sempre no banco 15. O `db=` de `from_url` perde para o número do
    banco que já vem na URL (`.../0`), por isso o banco é trocado na própria URL."""
    return urlparse(settings.redis_url)._replace(path="/15").geturl()


@pytest.fixture()
def redis_client(redis_test_url):
    client = redis.Redis.from_url(redis_test_url, decode_responses=True)
    # Trava de segurança: nunca esvaziar outro banco que não o 15.
    if client.connection_pool.connection_kwargs.get("db") != 15:
        client.close()
        raise RuntimeError("o Redis dos testes precisa ser o banco 15")
    client.flushdb()
    yield client
    client.flushdb()
    client.close()
