"""Ambiente do Alembic. Os testes passam uma conexão pronta (`config.attributes["connection"]`);
na linha de comando, a conexão vem de `server/.env`."""
from alembic import context
from sqlalchemy import create_engine, pool

from app.db.models import Base
from app.settings import load_settings

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # `schema` (só nos testes) isola a tabela de versões no esquema temporário; sem isso o
        # Alembic enxerga o `alembic_version` do `public` pelo search_path e pula as migrações.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=config.attributes.get("schema"),
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(load_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("as migrações só rodam com conexão ao banco (modo online)")
run_migrations_online()
