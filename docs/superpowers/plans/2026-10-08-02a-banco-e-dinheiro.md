# Banco, Redis e fluxo de dinheiro — Plano de implementação (plano 2A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar memória e segurança de dinheiro ao núcleo de regras: guardar tudo no PostgreSQL com migrações, guardar posições e reservas das motos no Redis, e ter um serviço transacional de pagamentos que cria a cobrança Pix, trata o aviso de "pago" sem repetir, cuida do vencimento, do cancelamento e do estorno, e nunca perdoa nem duplica dinheiro nem dívida. Sem HTTP.

**Architecture:** Camada `app/db` (modelos SQLAlchemy 2.0, migrações Alembic, repositórios que convertem entre linhas e os objetos do domínio do plano 1), `app/infra` (Redis) e `app/services` (casos de uso transacionais). O domínio do plano 1 continua puro; a persistência o chama e grava o resultado. Serviços nunca fazem `commit`: quem chama controla a transação, então uma falha no meio desfaz tudo. Ordem de travas no banco: corrida, depois motoqueiro, depois cobrança.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, psycopg 3, Alembic, redis-py 5, pytest 8, PostgreSQL 16 com PostGIS 3.4 e Redis 7 (já instalados; ver `server/.env`).

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 7, 10, 12). Este é o plano 2A de 8; ver `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`. Parte do plano 1: ver o adendo "Correções feitas depois da revisão final" em `2026-10-08-01-nucleo-de-regras.md`.

## Global Constraints

- Dinheiro sempre em **centavos inteiros** (`int`). Tempos do domínio em segundos (`float`).
- O livro-caixa **só acrescenta**: o próprio banco deve recusar `UPDATE`, `DELETE` e `TRUNCATE` na tabela de lançamentos.
- Cada aviso do provedor é tratado **uma vez só**; aviso repetido não cobra duas vezes.
- Pix é criado quando o motoqueiro aceita; o passageiro tem **120 s** para pagar (`RideConfig.pix_window_s`).
- A dívida de corridas em dinheiro só diminui quando o Pix é confirmado, e volta se o Pix pago for devolvido (plano 1, adendo).
- Serviços e repositórios **não fazem `commit`**. Ordem de travas: corrida → motoqueiro → cobrança.
- Segredos só em `server/.env` (já ignorado pelo git). Nunca em código, teste ou commit.
- Os testes **nunca** tocam o esquema `public` do banco de desenvolvimento: cada execução cria um esquema temporário próprio (`t_<aleatório>`), aplica as migrações nele e o apaga no fim. O Redis dos testes usa o banco número 15.
- Textos de erro em português do Brasil.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Todos os comandos abaixo partem da pasta `server/` (dentro de `/home/levy-anjos/Documentos/projetos/app-corrida-reconcavo`). PostgreSQL e Redis precisam estar rodando: `systemctl is-active postgresql redis-server` deve responder `active` duas vezes.

## Review Focus

1. **Aviso de "pago" repetido, aviso novo para cobrança já paga e aviso de cobrança antiga (de uma moto que já saiu da corrida).** O esperado é o dinheiro nunca ser contado duas vezes e a corrida atual nunca ser marcada como paga por uma cobrança velha, que deve ser devolvida (Tarefa 8).
2. **Pix que vence, corrida cancelada antes de pagar e fila liberada.** O esperado é a dívida reservada ser liberada e a dívida real ficar como estava, nunca perdoada nem presa (Tarefa 8).
3. **Livro-caixa alterado, apagado ou esvaziado direto no banco, ou lançamento duplicado.** O esperado é o próprio banco recusar (Tarefas 3 e 5).
4. **Provedor falha no meio de um estorno.** O esperado é nada ficar pela metade: ao desfazer a transação, o livro, a dívida e a corrida voltam ao que eram e o aviso pode ser tratado de novo (Tarefa 8).
5. **Reserva de moto que ninguém libera (falha no meio da oferta).** O esperado é a reserva expirar sozinha, e a moto não ficar presa para sempre (Tarefa 7).

---

### Task 1: Dependências e configuração

**Files:**
- Modify: `server/pyproject.toml`
- Create: `server/app/settings.py`
- Test: `server/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `Settings(database_url: str, redis_url: str)` (congelada). `database_url` já vem no formato SQLAlchemy (`postgresql+psycopg://...`).
  - `parse_env_file(path: Path) -> dict[str, str]`
  - `load_settings(env_path: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings` (variável de ambiente vence o arquivo; falta de valor levanta `RuntimeError`).

- [ ] **Step 1: Instalar as dependências e registrá-las**

Run: `.venv/bin/pip install -q "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" "redis>=5.0" && .venv/bin/python -c "import sqlalchemy, psycopg, alembic, redis; print('ok', sqlalchemy.__version__)"`
Expected: `ok 2.0.x`

Em `server/pyproject.toml`, trocar a linha `dependencies = []` por:

```toml
dependencies = [
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "alembic>=1.13",
    "redis>=5.0",
]
```

- [ ] **Step 2: Escrever os testes que falham**

`server/tests/test_settings.py`:

```python
import pytest

from app.settings import Settings, load_settings, parse_env_file


def test_le_o_arquivo_env_e_ajusta_o_driver(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comentário\n\nDATABASE_URL=postgresql://u:p@localhost:5432/db\nREDIS_URL=redis://localhost:6379/0\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env, environ={})
    assert settings == Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
    )


def test_variavel_de_ambiente_vence_o_arquivo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n", encoding="utf-8")
    settings = load_settings(env_path=env, environ={"REDIS_URL": "redis://b/1"})
    assert settings.redis_url == "redis://b/1"
    assert settings.database_url == "postgresql+psycopg://a@h/x"


def test_falta_de_configuracao_da_erro_claro(tmp_path):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        load_settings(env_path=tmp_path / "nao-existe", environ={})


def test_aspas_no_valor_sao_removidas(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="com aspas"\nB=\'simples\'\nC=sem\n', encoding="utf-8")
    assert parse_env_file(env) == {"A": "com aspas", "B": "simples", "C": "sem"}


def test_url_que_ja_tem_driver_nao_e_alterada(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql+psycopg://u@h/d\nREDIS_URL=redis://h/0\n", encoding="utf-8")
    assert load_settings(env_path=env, environ={}).database_url == "postgresql+psycopg://u@h/d"
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: `ModuleNotFoundError: No module named 'app.settings'`.

- [ ] **Step 4: Implementar**

`server/app/settings.py`:

```python
"""Configuração do servidor: variáveis de ambiente, com `server/.env` como reserva.

O arquivo `.env` guarda segredos (senha do banco) e fica fora do git.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _with_driver(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def load_settings(
    env_path: Path | None = None, environ: Mapping[str, str] | None = None
) -> Settings:
    file_values = parse_env_file(env_path or _DEFAULT_ENV_PATH)
    env = os.environ if environ is None else environ

    def get(key: str) -> str:
        value = env.get(key) or file_values.get(key)
        if not value:
            raise RuntimeError(f"falta a configuração {key} (defina no ambiente ou em server/.env)")
        return value

    return Settings(database_url=_with_driver(get("DATABASE_URL")), redis_url=get("REDIS_URL"))
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam (os 133 do plano 1 e os 5 novos).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/settings.py tests/test_settings.py && git commit -m "feat(server): dependências do banco e leitura de configuração do .env" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Ajustes no domínio para a persistência

**Files:**
- Modify: `server/app/domain/ledger.py`
- Modify: `server/app/domain/fees.py`
- Modify: `server/app/domain/payments.py`
- Test: `server/tests/domain/test_ledger.py`, `server/tests/domain/test_fees.py`, `server/tests/domain/test_payments.py` (acrescentar no fim de cada)

**Interfaces:**
- Produces:
  - `Ledger.from_entries(entries: Iterable[LedgerEntry]) -> Ledger` (classmethod; monta um livro em memória a partir de lançamentos que já existem).
  - `validate_fee_config` passa a recusar `max_debt_share` fora de 0 a 1.
  - `compute_split` passa a recusar `max_debt_share` fora de 0 a 1 (erro com a palavra "abatimento").

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `server/tests/domain/test_ledger.py`:

```python
def test_livro_pode_ser_montado_a_partir_de_lancamentos_existentes():
    original = _ledger_com_cobranca()
    copia = Ledger.from_entries(original.entries)
    assert copia.balance("rider:rider-1") == 600
    with pytest.raises(ValueError, match="já lançado"):
        copia.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))
    copia.post_refund("ch-1")
    assert copia.is_balanced() is True
    assert len(original.entries) == 3  # o original não muda
```

Acrescentar ao fim de `server/tests/domain/test_fees.py`:

```python
def test_limite_de_abatimento_fora_de_0_a_1_e_invalido():
    for ruim in (-0.1, 1.5):
        with pytest.raises(ValueError, match="abatimento"):
            validate_fee_config(FeeConfig(max_debt_share=ruim))
```

Acrescentar ao fim de `server/tests/domain/test_payments.py`:

```python
def test_divisao_com_limite_de_abatimento_invalido_da_erro():
    for ruim in (-0.1, 1.5):
        with pytest.raises(ValueError, match="abatimento"):
            compute_split(700, 100, 300, max_debt_share=ruim)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_ledger.py tests/domain/test_fees.py tests/domain/test_payments.py -q`
Expected: 3 falhas (`AttributeError ... from_entries` e dois `DID NOT RAISE`).

- [ ] **Step 3: Implementar**

Em `server/app/domain/ledger.py`, trocar o `import` do topo e acrescentar o método. Substituir a linha `from dataclasses import dataclass` por:

```python
from collections.abc import Iterable
from dataclasses import dataclass
```

e, logo depois do método `__init__` da classe `Ledger`, acrescentar:

```python
    @classmethod
    def from_entries(cls, entries: Iterable[LedgerEntry]) -> Ledger:
        """Livro em memória montado a partir de lançamentos que já existem (por exemplo, do banco)."""
        ledger = cls()
        ledger._entries = list(entries)
        return ledger
```

Em `server/app/domain/fees.py`, no início de `validate_fee_config`, antes de `if not cfg.tiers:`, acrescentar:

```python
    if not 0 <= cfg.max_debt_share <= 1:
        raise ValueError("o limite de abatimento da dívida precisa estar entre 0 e 1")
```

Em `server/app/domain/payments.py`, no início de `compute_split`, antes de `if price_cents <= 0 ...`, acrescentar:

```python
    if not 0 <= max_debt_share <= 1:
        raise ValueError("o limite de abatimento da dívida precisa estar entre 0 e 1")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/domain/ledger.py app/domain/fees.py app/domain/payments.py tests/domain/test_ledger.py tests/domain/test_fees.py tests/domain/test_payments.py && git commit -m "feat(domain): livro montado a partir de lançamentos e validação do limite de abatimento" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Modelos, migração inicial e esquema de testes

**Files:**
- Create: `server/app/db/__init__.py` (vazio)
- Create: `server/app/db/models.py`
- Create: `server/app/db/session.py`
- Create: `server/alembic.ini`
- Create: `server/migrations/env.py`
- Create: `server/migrations/script.py.mako`
- Create: `server/migrations/versions/0001_esquema_inicial.py`
- Create: `server/tests/conftest.py`
- Create: `server/tests/db/__init__.py` (vazio)
- Test: `server/tests/db/test_schema.py`

**Interfaces:**
- Produces:
  - `Base` e as linhas `UserRow`, `RiderProfileRow`, `PassengerProfileRow`, `RideRow`, `PixChargeRow`, `LedgerRow`, `ProcessedEventRow`, `AppConfigRow` (campos nos blocos abaixo).
  - `make_engine(settings: Settings) -> Engine` e `make_session_factory(engine: Engine) -> sessionmaker[Session]`.
  - Fixtures de teste: `settings` (sessão de testes), `db_engine` (sessão de testes; esquema temporário com as migrações aplicadas), `session` (por teste; tudo desfeito no fim), `redis_client` (por teste; Redis banco 15, esvaziado antes e depois).

- [ ] **Step 1: Escrever os testes e a infraestrutura de testes**

`server/tests/conftest.py`:

```python
"""Fixtures de banco e Redis. Cada execução usa um esquema temporário próprio no PostgreSQL de
desenvolvimento (nunca o `public`) e o banco 15 do Redis."""
import uuid
from pathlib import Path

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
        command.upgrade(cfg, "head")
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


@pytest.fixture()
def redis_client(settings):
    client = redis.Redis.from_url(settings.redis_url, db=15, decode_responses=True)
    client.flushdb()
    yield client
    client.flushdb()
    client.close()
```

`server/tests/db/test_schema.py`:

```python
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.models import (
    Base,
    LedgerRow,
    PixChargeRow,
    RideRow,
    RiderProfileRow,
    UserRow,
)
from app.db.session import make_session_factory


def _user(user_id: str, phone: str, role: str = "rider") -> UserRow:
    return UserRow(id=user_id, phone=phone, name=f"Usuário {user_id}", role=role)


def _rider(user_id: str, cpf: str, cnh: str, plate: str, **extra) -> RiderProfileRow:
    return RiderProfileRow(
        user_id=user_id, cpf=cpf, cnh_number=cnh, plate=plate, moto_model="Honda CG 160", **extra
    )


def test_migracao_cria_exatamente_as_tabelas_e_colunas_dos_modelos(db_engine):
    insp = inspect(db_engine)
    tabelas_no_banco = set(insp.get_table_names()) - {"alembic_version"}
    assert tabelas_no_banco == set(Base.metadata.tables)
    for nome, tabela in Base.metadata.tables.items():
        colunas_no_banco = {c["name"] for c in insp.get_columns(nome)}
        assert colunas_no_banco == {c.name for c in tabela.columns}, nome


def test_fabrica_de_sessao_conversa_com_o_banco(db_engine):
    with make_session_factory(db_engine)() as s:
        assert s.execute(text("select 1")).scalar() == 1


def test_livro_caixa_recusa_alterar_apagar_e_esvaziar(session):
    # Review Focus 3: quem protege o livro é o próprio banco.
    session.add(LedgerRow(ref="charge:ch-1", account="company", amount_cents=100, kind="ride_payment"))
    session.flush()
    for sql in (
        "UPDATE ledger_entries SET amount_cents = 1",
        "DELETE FROM ledger_entries",
        "TRUNCATE ledger_entries",
    ):
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(text(sql))
    assert session.execute(text("SELECT count(*) FROM ledger_entries")).scalar() == 1


def test_livro_caixa_recusa_lancamento_repetido_mas_aceita_correcoes(session):
    base = dict(ref="charge:ch-1", account="company", amount_cents=100)
    session.add(LedgerRow(kind="ride_payment", **base))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(LedgerRow(kind="ride_payment", **base))
            session.flush()
    session.add(LedgerRow(kind="correction", **base))
    session.add(LedgerRow(kind="correction", **base))
    session.flush()


@pytest.mark.parametrize("campo", ["cpf", "cnh", "placa"])
def test_cpf_cnh_e_placa_nao_podem_se_repetir(session, campo):
    session.add_all([_user("r1", "+5575900000001"), _user("r2", "+5575900000002")])
    session.add(_rider("r1", "111.111.111-11", "CNH0001", "AAA1A11"))
    session.flush()
    dados = {"cpf": "222.222.222-22", "cnh": "CNH0002", "placa": "BBB2B22"}
    dados[campo] = {"cpf": "111.111.111-11", "cnh": "CNH0001", "placa": "AAA1A11"}[campo]
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_rider("r2", dados["cpf"], dados["cnh"], dados["placa"]))
            session.flush()


def test_divida_reservada_nunca_passa_da_divida(session):
    session.add(_user("r1", "+5575900000001"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                _rider("r1", "111.111.111-11", "CNH0001", "AAA1A11", cash_debt_cents=100, debt_reserved_cents=500)
            )
            session.flush()


def test_divisao_da_cobranca_precisa_fechar_com_o_valor(session):
    session.add_all([_user("p1", "+5575900000003", "passenger"), _user("r1", "+5575900000001")])
    session.flush()
    session.add(
        RideRow(id="ride-1", passenger_id="p1", price_cents=700, payment_method="pix", pin="4821", state="searching")
    )
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PixChargeRow(
                    charge_id="ch-1", ride_id="ride-1", rider_id="r1",
                    amount_cents=700, rider_cents=100, company_cents=100, debt_paid_cents=0,
                )
            )
            session.flush()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/db/test_schema.py -v`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implementar os modelos e a sessão**

Criar o pacote vazio: `mkdir -p app/db migrations/versions tests/db && touch app/db/__init__.py tests/db/__init__.py`.

`server/app/db/models.py`:

```python
"""Tabelas do banco (SQLAlchemy 2.0).

A fonte da verdade do esquema são as migrações em `migrations/versions/`. Um teste confere que
migrações e modelos têm as mesmas tabelas e colunas.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))  # passenger | rider | admin
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiderProfileRow(Base):
    __tablename__ = "rider_profiles"
    __table_args__ = (
        CheckConstraint("cash_debt_cents >= 0", name="rider_debt_non_negative"),
        CheckConstraint("debt_reserved_cents >= 0", name="rider_reserved_non_negative"),
        CheckConstraint("debt_reserved_cents <= cash_debt_cents", name="rider_reserved_within_debt"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    cpf: Mapped[str] = mapped_column(String(14), unique=True)
    cnh_number: Mapped[str] = mapped_column(String(20), unique=True)
    plate: Mapped[str] = mapped_column(String(10), unique=True)
    moto_model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    completed_rides: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    entry_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cash_debt_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    debt_reserved_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassengerProfileRow(Base):
    __tablename__ = "passenger_profiles"
    __table_args__ = (CheckConstraint("unpaid_cents >= 0", name="passenger_unpaid_non_negative"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    unpaid_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class RideRow(Base):
    __tablename__ = "rides"
    __table_args__ = (CheckConstraint("price_cents > 0", name="ride_price_positive"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    rider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(8))  # pix | cash
    pin: Mapped[str] = mapped_column(String(4))
    state: Mapped[str] = mapped_column(String(16))
    helmet_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    pix_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    pix_charge_created_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    searching_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    queued_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    en_route_since: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    arrived_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    end_payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    non_payment_reported: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    current_charge_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PixChargeRow(Base):
    __tablename__ = "pix_charges"
    __table_args__ = (
        CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
    )

    charge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    rider_cents: Mapped[int] = mapped_column(Integer)
    company_cents: Mapped[int] = mapped_column(Integer)
    debt_paid_cents: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    debt_state: Mapped[str] = mapped_column(String(12), default="reserved", server_default="reserved")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerRow(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index(
            "ledger_once_per_kind", "ref", "kind", "account",
            unique=True, postgresql_where=text("kind <> 'correction'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ref: Mapped[str] = mapped_column(String(80), index=True)
    account: Mapped[str] = mapped_column(String(80))
    amount_cents: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedEventRow(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    processed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppConfigRow(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`server/app/db/session.py`:

```python
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 4: Implementar a configuração do Alembic e a migração inicial**

`server/alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
```

`server/migrations/env.py`:

```python
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
        context.configure(connection=connection, target_metadata=target_metadata)
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
```

`server/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`server/migrations/versions/0001_esquema_inicial.py`:

```python
"""esquema inicial: usuários, perfis, corridas, cobranças Pix, livro-caixa, eventos e configuração

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_NOW = sa.func.now()


def _false() -> sa.TextClause:
    return sa.text("false")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "rider_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("cpf", sa.String(14), nullable=False, unique=True),
        sa.Column("cnh_number", sa.String(20), nullable=False, unique=True),
        sa.Column("plate", sa.String(10), nullable=False, unique=True),
        sa.Column("moto_model", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("completed_rides", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("entry_paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("cash_debt_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("debt_reserved_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cash_debt_cents >= 0", name="rider_debt_non_negative"),
        sa.CheckConstraint("debt_reserved_cents >= 0", name="rider_reserved_non_negative"),
        sa.CheckConstraint("debt_reserved_cents <= cash_debt_cents", name="rider_reserved_within_debt"),
    )
    op.create_table(
        "passenger_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("unpaid_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("unpaid_cents >= 0", name="passenger_unpaid_non_negative"),
    )
    op.create_table(
        "rides",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(8), nullable=False),
        sa.Column("pin", sa.String(4), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("helmet_confirmed", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("pix_paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("pix_charge_created_at", sa.Float(53), nullable=True),
        sa.Column("searching_since", sa.Float(53), nullable=True),
        sa.Column("queued_since", sa.Float(53), nullable=True),
        sa.Column("en_route_since", sa.Float(53), nullable=True),
        sa.Column("arrived_at", sa.Float(53), nullable=True),
        sa.Column("end_payment_confirmed", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("non_payment_reported", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("current_charge_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("price_cents > 0", name="ride_price_positive"),
    )
    op.create_table(
        "pix_charges",
        sa.Column("charge_id", sa.String(40), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("rider_cents", sa.Integer(), nullable=False),
        sa.Column("company_cents", sa.Integer(), nullable=False),
        sa.Column("debt_paid_cents", sa.Integer(), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("refunded", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("debt_state", sa.String(12), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ref", sa.String(80), nullable=False),
        sa.Column("account", sa.String(80), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_ledger_entries_ref", "ledger_entries", ["ref"])
    op.create_index(
        "ledger_once_per_kind",
        "ledger_entries",
        ["ref", "kind", "account"],
        unique=True,
        postgresql_where=sa.text("kind <> 'correction'"),
    )
    op.execute(
        """
        CREATE FUNCTION ledger_no_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'o livro-caixa so aceita novos lancamentos';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER ledger_append_only BEFORE UPDATE OR DELETE ON ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION ledger_no_change()"
    )
    op.execute(
        "CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON ledger_entries "
        "FOR EACH STATEMENT EXECUTE FUNCTION ledger_no_change()"
    )
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(120), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_table("processed_events")
    op.execute("DROP TRIGGER ledger_no_truncate ON ledger_entries")
    op.execute("DROP TRIGGER ledger_append_only ON ledger_entries")
    op.execute("DROP FUNCTION ledger_no_change()")
    op.drop_table("ledger_entries")
    op.drop_table("pix_charges")
    op.drop_table("rides")
    op.drop_table("passenger_profiles")
    op.drop_table("rider_profiles")
    op.drop_table("users")
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/bin/pytest tests/db/test_schema.py -v`
Expected: todos passam (9 testes: 1 de esquema, 1 de sessão, 2 do livro, 3 da parametrização e 2 de restrições).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 6: Aplicar a migração no banco de desenvolvimento e conferir**

Run: `.venv/bin/alembic upgrade head && set -a && . ./.env && set +a && psql "$DATABASE_URL" -c '\dt'`
Expected: a lista mostra `alembic_version`, `app_config`, `ledger_entries`, `passenger_profiles`, `pix_charges`, `processed_events`, `rider_profiles`, `rides` e `users`.

- [ ] **Step 7: Commit**

```bash
git add app/db alembic.ini migrations tests/conftest.py tests/db && git commit -m "feat(db): modelos, migração inicial com livro-caixa protegido e esquema temporário de testes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Repositórios

**Files:**
- Create: `server/app/db/repositories.py`
- Create: `server/tests/helpers_db.py`
- Test: `server/tests/db/test_repositories.py`

**Interfaces:**
- Consumes: modelos (tarefa 3); `RiderAccount` (plano 1, `app.domain.fees`); `PassengerAccount`, `Ride`, `RideState` (`app.domain.rides`); `PixCharge`, `Split`, `DebtState` (`app.domain.payments`); `PaymentMethod`.
- Produces (todas recebem `session` como primeiro parâmetro e **não fazem commit**):
  - `add_user(session, *, user_id, phone, name, role) -> None`
  - `add_rider_profile(session, *, user_id, cpf, cnh_number, plate, moto_model, status="pending") -> None`
  - `get_rider_account(session, rider_id, *, for_update=False) -> RiderAccount`; `save_rider_account(session, acc) -> None`
  - `add_passenger_profile(session, *, user_id) -> None`
  - `get_passenger_account(session, passenger_id, *, for_update=False) -> PassengerAccount`; `save_passenger_account(session, acc) -> None`
  - `add_ride(session, ride) -> None`; `get_ride(session, ride_id, *, for_update=False) -> Ride`; `save_ride(session, ride) -> None`
  - `set_current_charge(session, ride_id, charge_id: str | None) -> None`; `get_current_charge_id(session, ride_id) -> str | None`
  - `add_charge(session, charge) -> None`; `get_charge(session, charge_id, *, for_update=False) -> PixCharge`; `save_charge(session, charge) -> None`
  - `first_time_event(session, event_id) -> bool` (grava o evento e diz se era a primeira vez)
  - Em `tests/helpers_db.py`: `add_passenger(session, user_id="p1", phone=...)`, `add_rider(session, user_id="r1", phone=..., cpf=..., cnh=..., plate=..., debt_cents=0)`, `add_accepted_ride(session, ride_id="ride-1", passenger_id="p1", rider_id="r1", method=PaymentMethod.PIX, price=700, busy=False, now=10.0) -> Ride`.
  - Funções que não encontram a linha levantam `LookupError`.

- [ ] **Step 1: Escrever os testes e os ajudantes**

`server/tests/helpers_db.py`:

```python
"""Montagem rápida de pessoas e corridas no banco de testes."""
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.domain.rides import Ride, accept, start_search
from app.domain.types import PaymentMethod


def add_passenger(session: Session, user_id: str = "p1", phone: str = "+5575900000001") -> None:
    repo.add_user(session, user_id=user_id, phone=phone, name=f"Passageiro {user_id}", role="passenger")
    repo.add_passenger_profile(session, user_id=user_id)


def add_rider(
    session: Session,
    user_id: str = "r1",
    phone: str = "+5575900000002",
    cpf: str = "111.111.111-11",
    cnh: str = "CNH0001",
    plate: str = "AAA1A11",
    debt_cents: int = 0,
) -> None:
    repo.add_user(session, user_id=user_id, phone=phone, name=f"Motoqueiro {user_id}", role="rider")
    repo.add_rider_profile(
        session, user_id=user_id, cpf=cpf, cnh_number=cnh, plate=plate, moto_model="Honda CG 160"
    )
    if debt_cents:
        acc = repo.get_rider_account(session, user_id)
        acc.cash_debt_cents = debt_cents
        repo.save_rider_account(session, acc)


def add_accepted_ride(
    session: Session,
    ride_id: str = "ride-1",
    passenger_id: str = "p1",
    rider_id: str = "r1",
    method: PaymentMethod = PaymentMethod.PIX,
    price: int = 700,
    busy: bool = False,
    now: float = 10.0,
) -> Ride:
    ride = Ride(ride_id, passenger_id, price, method, pin="4821")
    start_search(ride, 0)
    accept(ride, rider_id, now, rider_busy=busy)
    repo.add_ride(session, ride)
    return ride
```

`server/tests/db/test_repositories.py`:

```python
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.fees import RiderAccount
from app.domain.payments import DebtState, compute_split
from app.domain.rides import PassengerAccount, confirm_pix_paid
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_motoqueiro_novo_comeca_sem_corridas_nem_divida(session):
    add_rider(session)
    assert repo.get_rider_account(session, "r1") == RiderAccount("r1")


def test_conta_do_motoqueiro_vai_e_volta(session):
    add_rider(session)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 11
    acc.entry_paid = True
    acc.cash_debt_cents = 500
    acc.debt_reserved_cents = 200
    repo.save_rider_account(session, acc)
    session.expire_all()
    assert repo.get_rider_account(session, "r1") == acc


def test_motoqueiro_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_rider_account(session, "ninguem")


def test_conta_do_passageiro_vai_e_volta(session):
    add_passenger(session)
    assert repo.get_passenger_account(session, "p1") == PassengerAccount("p1")
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    session.expire_all()
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 700


def test_corrida_vai_e_volta_com_todos_os_campos(session):
    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session, busy=True)  # fica na fila
    session.expire_all()
    assert repo.get_ride(session, "ride-1") == ride
    confirm_pix_paid(ride)
    repo.save_ride(session, ride)
    session.expire_all()
    carregada = repo.get_ride(session, "ride-1")
    assert carregada == ride
    assert carregada.pix_paid is True


def test_corrida_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_ride(session, "nao-existe")


def test_cobranca_atual_da_corrida(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    assert repo.get_current_charge_id(session, "ride-1") is None
    repo.set_current_charge(session, "ride-1", "ch-1")
    assert repo.get_current_charge_id(session, "ride-1") == "ch-1"
    repo.set_current_charge(session, "ride-1", None)
    assert repo.get_current_charge_id(session, "ride-1") is None


def test_cobranca_vai_e_volta(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 300))
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge
    charge.paid = True
    charge.refunded = True
    charge.debt_state = DebtState.RESTORED
    repo.save_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge


def test_cobranca_inexistente_da_erro(session):
    with pytest.raises(LookupError):
        repo.get_charge(session, "ch-99")


def test_evento_so_conta_a_primeira_vez(session):
    # Review Focus 1: a trava contra aviso repetido é uma chave única no banco.
    assert repo.first_time_event(session, "evt-1") is True
    assert repo.first_time_event(session, "evt-1") is False
    assert repo.first_time_event(session, "evt-2") is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/db/test_repositories.py -v`
Expected: `ImportError` (não existe `app.db.repositories`).

- [ ] **Step 3: Implementar**

`server/app/db/repositories.py`:

```python
"""Leitura e gravação dos objetos do domínio no PostgreSQL.

Nenhuma função faz commit: quem chama controla a transação. Quando uma operação precisa travar
várias linhas, a ordem é sempre corrida, motoqueiro, cobrança (evita impasse entre transações).
"""
from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    PassengerProfileRow,
    PixChargeRow,
    ProcessedEventRow,
    RideRow,
    RiderProfileRow,
    UserRow,
)
from app.domain.fees import RiderAccount
from app.domain.payments import DebtState, PixCharge, Split
from app.domain.rides import PassengerAccount, Ride, RideState
from app.domain.types import PaymentMethod


def _locking(stmt: Select, for_update: bool) -> Select:
    if for_update:
        return stmt.with_for_update().execution_options(populate_existing=True)
    return stmt


# --- pessoas -----------------------------------------------------------------


def add_user(session: Session, *, user_id: str, phone: str, name: str, role: str) -> None:
    session.add(UserRow(id=user_id, phone=phone, name=name, role=role))
    session.flush()


def add_rider_profile(
    session: Session,
    *,
    user_id: str,
    cpf: str,
    cnh_number: str,
    plate: str,
    moto_model: str,
    status: str = "pending",
) -> None:
    session.add(
        RiderProfileRow(
            user_id=user_id, cpf=cpf, cnh_number=cnh_number, plate=plate,
            moto_model=moto_model, status=status,
        )
    )
    session.flush()


def get_rider_account(session: Session, rider_id: str, *, for_update: bool = False) -> RiderAccount:
    stmt = _locking(select(RiderProfileRow).where(RiderProfileRow.user_id == rider_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"motoqueiro {rider_id} não encontrado")
    return RiderAccount(
        rider_id=row.user_id,
        completed_rides=row.completed_rides,
        entry_paid=row.entry_paid,
        cash_debt_cents=row.cash_debt_cents,
        debt_reserved_cents=row.debt_reserved_cents,
    )


def save_rider_account(session: Session, acc: RiderAccount) -> None:
    row = session.get(RiderProfileRow, acc.rider_id)
    if row is None:
        raise LookupError(f"motoqueiro {acc.rider_id} não encontrado")
    row.completed_rides = acc.completed_rides
    row.entry_paid = acc.entry_paid
    row.cash_debt_cents = acc.cash_debt_cents
    row.debt_reserved_cents = acc.debt_reserved_cents
    session.flush()


def add_passenger_profile(session: Session, *, user_id: str) -> None:
    session.add(PassengerProfileRow(user_id=user_id))
    session.flush()


def get_passenger_account(
    session: Session, passenger_id: str, *, for_update: bool = False
) -> PassengerAccount:
    stmt = _locking(
        select(PassengerProfileRow).where(PassengerProfileRow.user_id == passenger_id), for_update
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    return PassengerAccount(passenger_id=row.user_id, unpaid_cents=row.unpaid_cents)


def save_passenger_account(session: Session, acc: PassengerAccount) -> None:
    row = session.get(PassengerProfileRow, acc.passenger_id)
    if row is None:
        raise LookupError(f"passageiro {acc.passenger_id} não encontrado")
    row.unpaid_cents = acc.unpaid_cents
    session.flush()


# --- corridas ----------------------------------------------------------------


def _ride_to_domain(row: RideRow) -> Ride:
    return Ride(
        ride_id=row.id,
        passenger_id=row.passenger_id,
        price_cents=row.price_cents,
        payment_method=PaymentMethod(row.payment_method),
        pin=row.pin,
        state=RideState(row.state),
        rider_id=row.rider_id,
        helmet_confirmed=row.helmet_confirmed,
        pix_paid=row.pix_paid,
        pix_charge_created_at=row.pix_charge_created_at,
        searching_since=row.searching_since,
        queued_since=row.queued_since,
        en_route_since=row.en_route_since,
        arrived_at=row.arrived_at,
        end_payment_confirmed=row.end_payment_confirmed,
        non_payment_reported=row.non_payment_reported,
    )


def _apply_ride(row: RideRow, ride: Ride) -> None:
    row.passenger_id = ride.passenger_id
    row.rider_id = ride.rider_id
    row.price_cents = ride.price_cents
    row.payment_method = ride.payment_method.value
    row.pin = ride.pin
    row.state = ride.state.value
    row.helmet_confirmed = ride.helmet_confirmed
    row.pix_paid = ride.pix_paid
    row.pix_charge_created_at = ride.pix_charge_created_at
    row.searching_since = ride.searching_since
    row.queued_since = ride.queued_since
    row.en_route_since = ride.en_route_since
    row.arrived_at = ride.arrived_at
    row.end_payment_confirmed = ride.end_payment_confirmed
    row.non_payment_reported = ride.non_payment_reported


def add_ride(session: Session, ride: Ride) -> None:
    row = RideRow(id=ride.ride_id)
    _apply_ride(row, ride)
    session.add(row)
    session.flush()


def get_ride(session: Session, ride_id: str, *, for_update: bool = False) -> Ride:
    stmt = _locking(select(RideRow).where(RideRow.id == ride_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    return _ride_to_domain(row)


def save_ride(session: Session, ride: Ride) -> None:
    row = session.get(RideRow, ride.ride_id)
    if row is None:
        raise LookupError(f"corrida {ride.ride_id} não encontrada")
    _apply_ride(row, ride)
    session.flush()


def set_current_charge(session: Session, ride_id: str, charge_id: str | None) -> None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    row.current_charge_id = charge_id
    session.flush()


def get_current_charge_id(session: Session, ride_id: str) -> str | None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    return row.current_charge_id


# --- cobranças e eventos --------------------------------------------------------


def _charge_to_domain(row: PixChargeRow) -> PixCharge:
    return PixCharge(
        charge_id=row.charge_id,
        ride_id=row.ride_id,
        rider_id=row.rider_id,
        amount_cents=row.amount_cents,
        split=Split(
            rider_cents=row.rider_cents,
            company_cents=row.company_cents,
            debt_paid_cents=row.debt_paid_cents,
        ),
        paid=row.paid,
        refunded=row.refunded,
        debt_state=DebtState(row.debt_state),
    )


def _apply_charge(row: PixChargeRow, charge: PixCharge) -> None:
    row.ride_id = charge.ride_id
    row.rider_id = charge.rider_id
    row.amount_cents = charge.amount_cents
    row.rider_cents = charge.split.rider_cents
    row.company_cents = charge.split.company_cents
    row.debt_paid_cents = charge.split.debt_paid_cents
    row.paid = charge.paid
    row.refunded = charge.refunded
    row.debt_state = charge.debt_state.value


def add_charge(session: Session, charge: PixCharge) -> None:
    row = PixChargeRow(charge_id=charge.charge_id)
    _apply_charge(row, charge)
    session.add(row)
    session.flush()


def get_charge(session: Session, charge_id: str, *, for_update: bool = False) -> PixCharge:
    stmt = _locking(select(PixChargeRow).where(PixChargeRow.charge_id == charge_id), for_update)
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise LookupError(f"cobrança {charge_id} não encontrada")
    return _charge_to_domain(row)


def save_charge(session: Session, charge: PixCharge) -> None:
    row = session.get(PixChargeRow, charge.charge_id)
    if row is None:
        raise LookupError(f"cobrança {charge.charge_id} não encontrada")
    _apply_charge(row, charge)
    session.flush()


def first_time_event(session: Session, event_id: str) -> bool:
    """Grava o aviso do provedor. Devolve True se ele nunca tinha sido visto (chave única no banco)."""
    stmt = (
        pg_insert(ProcessedEventRow)
        .values(event_id=event_id)
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(ProcessedEventRow.event_id)
    )
    return session.execute(stmt).scalar_one_or_none() is not None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/db/test_repositories.py -v`
Expected: todos passam (10 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/db/repositories.py tests/helpers_db.py tests/db/test_repositories.py && git commit -m "feat(db): repositórios que convertem entre linhas do banco e objetos do domínio" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Livro-caixa persistente

**Files:**
- Create: `server/app/db/pg_ledger.py`
- Test: `server/tests/db/test_pg_ledger.py`

**Interfaces:**
- Consumes: `Ledger`, `LedgerEntry`, `EntryKind` (`app.domain.ledger`), `Split` (`app.domain.payments`), `LedgerRow` (tarefa 3).
- Produces: `PgLedger(session)` com os mesmos métodos do `Ledger` do domínio: `post_charge_payment(charge_id, rider_id, price_cents, split)`, `post_refund(charge_id)`, `post_entry_fee(rider_id, amount_cents)`, `post_correction(ref, lines, reason)`, `balance(account) -> int`, `is_balanced() -> bool`, `reconcile(provider_received_by_ref) -> dict[str, int]`, e as constantes `PgLedger.PROVIDER` e `PgLedger.COMPANY`. As regras (soma zero, sem duplicar, sem estorno duplo) vêm do `Ledger` do domínio, reaproveitado, e o banco repete a proteção contra duplicados.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/db/test_pg_ledger.py`:

```python
import pytest
from sqlalchemy import text

from app.db.models import LedgerRow
from app.db.pg_ledger import PgLedger
from app.domain.payments import Split, compute_split


def _com_cobranca(session) -> PgLedger:
    ledger = PgLedger(session)
    ledger.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_fecha_em_zero_e_os_saldos_batem(session):
    ledger = _com_cobranca(session)
    assert ledger.is_balanced() is True
    assert ledger.balance("rider:rider-1") == 600
    assert ledger.balance(PgLedger.COMPANY) == 100
    assert ledger.balance(PgLedger.PROVIDER) == -700


def test_um_segundo_objeto_enxerga_o_que_o_primeiro_gravou(session):
    _com_cobranca(session)
    outro = PgLedger(session)
    assert outro.balance("rider:rider-1") == 600
    with pytest.raises(ValueError, match="já lançado"):
        outro.post_charge_payment("ch-1", "rider-1", 700, compute_split(700, 100))


def test_divisao_que_nao_fecha_e_recusada_e_nada_e_gravado(session):
    ledger = PgLedger(session)
    with pytest.raises(ValueError, match="divisão"):
        ledger.post_charge_payment("ch-1", "rider-1", 700, Split(500, 100, 0))
    assert session.execute(text("SELECT count(*) FROM ledger_entries")).scalar() == 0


def test_estorno_zera_os_saldos(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.balance(PgLedger.PROVIDER) == 0
    assert ledger.is_balanced() is True


def test_estorno_duplo_e_estorno_sem_pagamento_sao_recusados(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    with pytest.raises(ValueError, match="já devolvida"):
        ledger.post_refund("ch-1")
    with pytest.raises(ValueError, match="não encontrado"):
        ledger.post_refund("ch-9")


def test_corrida_que_troca_de_moto_tem_duas_cobrancas_no_livro(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    ledger.post_charge_payment("ch-2", "rider-2", 700, compute_split(700, 100))
    assert ledger.balance("rider:rider-2") == 600
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.is_balanced() is True


def test_taxa_de_entrada_e_so_uma_vez(session):
    ledger = PgLedger(session)
    ledger.post_entry_fee("rider-1", 5000)
    assert ledger.balance(PgLedger.COMPANY) == 5000
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_entry_fee("rider-1", 5000)


def test_correcao_balanceada_e_registrada(session):
    ledger = _com_cobranca(session)
    ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], "ajuste de taxa")
    assert ledger.balance(PgLedger.COMPANY) == 50
    assert ledger.balance("rider:rider-1") == 650
    assert ledger.is_balanced() is True


def test_correcoes_invalidas_sao_recusadas(session):
    ledger = _com_cobranca(session)
    with pytest.raises(ValueError, match="zero"):
        ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50)], "erro")
    with pytest.raises(ValueError, match="motivo"):
        ledger.post_correction("charge:ch-1", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], " ")
    with pytest.raises(ValueError, match="desconhecida"):
        ledger.post_correction("charge:nao-existe", [(PgLedger.COMPANY, -50), ("rider:rider-1", 50)], "x")


def test_conciliacao_aponta_diferencas(session):
    ledger = _com_cobranca(session)
    assert ledger.reconcile({"charge:ch-1": 700}) == {}
    assert ledger.reconcile({"charge:ch-1": 600}) == {"charge:ch-1": -100}
    assert ledger.reconcile({}) == {"charge:ch-1": -700}
    assert ledger.reconcile({"charge:ch-1": 700, "charge:ch-9": 500}) == {"charge:ch-9": 500}


def test_conciliacao_depois_de_estorno_nao_acusa_diferenca(session):
    ledger = _com_cobranca(session)
    ledger.post_refund("ch-1")
    assert ledger.reconcile({}) == {}


def test_lancamento_solto_que_nao_fecha_e_detectado(session):
    ledger = PgLedger(session)
    session.add(LedgerRow(ref="charge:ch-x", account="company", amount_cents=100, kind="ride_payment"))
    session.flush()
    assert ledger.is_balanced() is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/db/test_pg_ledger.py -v`
Expected: `ModuleNotFoundError: No module named 'app.db.pg_ledger'`.

- [ ] **Step 3: Implementar**

`server/app/db/pg_ledger.py`:

```python
"""Livro-caixa gravado no PostgreSQL (spec, seção 7.6).

As regras (cada cobrança soma zero, sem pagamento nem estorno repetidos, correções balanceadas)
são as do `Ledger` do domínio: cada operação carrega os lançamentos da referência, deixa o domínio
validar e grava só os lançamentos novos. O banco repete a proteção: chave única contra repetição e
gatilhos que recusam alterar, apagar ou esvaziar a tabela.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LedgerRow
from app.domain.ledger import EntryKind, Ledger, LedgerEntry
from app.domain.payments import Split


class PgLedger:
    PROVIDER = Ledger.PROVIDER
    COMPANY = Ledger.COMPANY

    def __init__(self, session: Session) -> None:
        self.session = session

    def _load(self, ref: str) -> Ledger:
        rows = self.session.execute(
            select(LedgerRow).where(LedgerRow.ref == ref).order_by(LedgerRow.id)
        ).scalars()
        return Ledger.from_entries(
            LedgerEntry(r.id, r.ref, r.account, r.amount_cents, EntryKind(r.kind), r.note) for r in rows
        )

    def _store_new(self, ledger: Ledger, already: int) -> None:
        for e in ledger.entries[already:]:
            self.session.add(
                LedgerRow(ref=e.ref, account=e.account, amount_cents=e.amount_cents, kind=e.kind.value, note=e.note)
            )
        self.session.flush()

    def post_charge_payment(self, charge_id: str, rider_id: str, price_cents: int, split: Split) -> None:
        ledger = self._load(f"charge:{charge_id}")
        before = len(ledger.entries)
        ledger.post_charge_payment(charge_id, rider_id, price_cents, split)
        self._store_new(ledger, before)

    def post_refund(self, charge_id: str) -> None:
        ledger = self._load(f"charge:{charge_id}")
        before = len(ledger.entries)
        ledger.post_refund(charge_id)
        self._store_new(ledger, before)

    def post_entry_fee(self, rider_id: str, amount_cents: int) -> None:
        ledger = self._load(f"entry:{rider_id}")
        before = len(ledger.entries)
        ledger.post_entry_fee(rider_id, amount_cents)
        self._store_new(ledger, before)

    def post_correction(self, ref: str, lines: list[tuple[str, int]], reason: str) -> None:
        ledger = self._load(ref)
        before = len(ledger.entries)
        ledger.post_correction(ref, lines, reason)
        self._store_new(ledger, before)

    def balance(self, account: str) -> int:
        total = self.session.execute(
            select(func.coalesce(func.sum(LedgerRow.amount_cents), 0)).where(LedgerRow.account == account)
        ).scalar_one()
        return int(total)

    def is_balanced(self) -> bool:
        unbalanced = self.session.execute(
            select(LedgerRow.ref).group_by(LedgerRow.ref).having(func.sum(LedgerRow.amount_cents) != 0)
        ).first()
        return unbalanced is None

    def reconcile(self, provider_received_by_ref: dict[str, int]) -> dict[str, int]:
        rows = self.session.execute(
            select(LedgerRow).where(LedgerRow.account == self.PROVIDER).order_by(LedgerRow.id)
        ).scalars()
        provider_only = Ledger.from_entries(
            LedgerEntry(r.id, r.ref, r.account, r.amount_cents, EntryKind(r.kind), r.note) for r in rows
        )
        return provider_only.reconcile(provider_received_by_ref)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/db/test_pg_ledger.py -v`
Expected: todos passam (12 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/db/pg_ledger.py tests/db/test_pg_ledger.py && git commit -m "feat(db): livro-caixa persistente que reaproveita as regras do domínio" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Configuração no banco

**Files:**
- Create: `server/app/db/config_store.py`
- Test: `server/tests/db/test_config_store.py`

**Interfaces:**
- Consumes: as dataclasses de configuração (plano 1, `app.domain.config`), `validate_fee_config`, `AppConfigRow`.
- Produces:
  - `AppConfig(pricing: PricingConfig, fees: FeeConfig, rides: RideConfig, dispatch: DispatchConfig, safety: SafetyConfig)` (congelada).
  - `save_config(session, key: str, cfg) -> None` (chaves: `"pricing"`, `"fees"`, `"rides"`, `"dispatch"`, `"safety"`; recusa chave desconhecida, tipo errado e faixas de taxa inválidas com `ValueError`).
  - `load_config(session, key: str)` (devolve o padrão se não houver nada salvo; dados corrompidos levantam `ValueError` com a palavra "inválida").
  - `load_app_config(session) -> AppConfig`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/db/test_config_store.py`:

```python
import json

import pytest
from sqlalchemy import text

from app.db.config_store import AppConfig, load_app_config, load_config, save_config
from app.domain.config import (
    DispatchConfig,
    FeeConfig,
    FeeTier,
    PricingConfig,
    RideConfig,
    SafetyConfig,
)


def test_sem_nada_salvo_usa_os_padroes(session):
    assert load_app_config(session) == AppConfig(
        PricingConfig(), FeeConfig(), RideConfig(), DispatchConfig(), SafetyConfig()
    )


def test_salva_e_le_a_configuracao_de_preco(session):
    custom = PricingConfig(base_fare_cents=400, per_km_cents=200, min_price_cents=600)
    save_config(session, "pricing", custom)
    assert load_config(session, "pricing") == custom
    assert load_app_config(session).pricing == custom


def test_salva_e_le_as_faixas_de_taxa(session):
    custom = FeeConfig(tiers=(FeeTier(1, 3, 120), FeeTier(4, None, 100)), cash_debt_limit_cents=2000)
    save_config(session, "fees", custom)
    session.expire_all()
    assert load_config(session, "fees") == custom


def test_salvar_de_novo_substitui_o_valor(session):
    save_config(session, "rides", RideConfig(pix_window_s=90))
    save_config(session, "rides", RideConfig(pix_window_s=150))
    assert load_config(session, "rides").pix_window_s == 150


def test_faixa_abaixo_do_piso_nao_e_salva(session):
    ruim = FeeConfig(tiers=(FeeTier(1, None, 10),))
    with pytest.raises(ValueError, match="piso"):
        save_config(session, "fees", ruim)
    assert load_config(session, "fees") == FeeConfig()


def test_chave_desconhecida_e_tipo_errado_sao_recusados(session):
    with pytest.raises(ValueError, match="desconhecida"):
        save_config(session, "outra", PricingConfig())
    with pytest.raises(ValueError, match="tipo"):
        save_config(session, "pricing", FeeConfig())
    with pytest.raises(ValueError, match="desconhecida"):
        load_config(session, "outra")


def _gravar_cru(session, key: str, valor: dict) -> None:
    session.execute(
        text("INSERT INTO app_config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": json.dumps(valor)},
    )


def test_dados_corrompidos_no_banco_dao_erro_claro(session):
    # Review final do plano 1: configuração ruim não pode virar valor perigoso em silêncio.
    _gravar_cru(session, "fees", {"tiers": [{"from_ride": 1, "to_ride": None, "fee_cents": 10}], "min_fee_cents": 70,
                                  "trial_rides": 10, "entry_fee_cents": 5000, "cash_debt_limit_cents": 1000,
                                  "max_debt_share": 0.5})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "fees")


def test_campo_desconhecido_ou_faltando_no_banco_da_erro_claro(session):
    _gravar_cru(session, "pricing", {"base_fare_cents": 300, "campo_novo": 1})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "pricing")
    _gravar_cru(session, "fees", {"min_fee_cents": 70})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "fees")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/db/test_config_store.py -v`
Expected: `ModuleNotFoundError: No module named 'app.db.config_store'`.

- [ ] **Step 3: Implementar**

`server/app/db/config_store.py`:

```python
"""Números ajustáveis guardados no banco (tabela `app_config`), com validação ao salvar e ao ler."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import AppConfigRow
from app.domain.config import (
    DispatchConfig,
    FeeConfig,
    FeeTier,
    PricingConfig,
    RideConfig,
    SafetyConfig,
)
from app.domain.fees import validate_fee_config

_TYPES = {
    "pricing": PricingConfig,
    "fees": FeeConfig,
    "rides": RideConfig,
    "dispatch": DispatchConfig,
    "safety": SafetyConfig,
}


@dataclass(frozen=True)
class AppConfig:
    pricing: PricingConfig
    fees: FeeConfig
    rides: RideConfig
    dispatch: DispatchConfig
    safety: SafetyConfig


def _check_key(key: str) -> type:
    if key not in _TYPES:
        raise ValueError(f"chave de configuração desconhecida: {key}")
    return _TYPES[key]


def _from_json(key: str, data: dict):
    cls = _check_key(key)
    try:
        if key == "fees":
            data = {**data, "tiers": tuple(FeeTier(**t) for t in data["tiers"])}
        cfg = cls(**data)
    except (TypeError, KeyError) as exc:
        raise ValueError(f"configuração '{key}' inválida no banco: {exc!r}") from exc
    if key == "fees":
        try:
            validate_fee_config(cfg)
        except ValueError as exc:
            raise ValueError(f"configuração 'fees' inválida no banco: {exc}") from exc
    return cfg


def save_config(session: Session, key: str, cfg) -> None:
    cls = _check_key(key)
    if not isinstance(cfg, cls):
        raise ValueError(f"tipo errado para '{key}': esperado {cls.__name__}")
    if key == "fees":
        validate_fee_config(cfg)
    value = asdict(cfg)
    stmt = pg_insert(AppConfigRow).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": value, "updated_at": func.now()}
    )
    session.execute(stmt)


def load_config(session: Session, key: str):
    cls = _check_key(key)
    data = session.execute(select(AppConfigRow.value).where(AppConfigRow.key == key)).scalar_one_or_none()
    if data is None:
        return cls()
    return _from_json(key, data)


def load_app_config(session: Session) -> AppConfig:
    return AppConfig(
        pricing=load_config(session, "pricing"),
        fees=load_config(session, "fees"),
        rides=load_config(session, "rides"),
        dispatch=load_config(session, "dispatch"),
        safety=load_config(session, "safety"),
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/db/test_config_store.py -v`
Expected: todos passam (8 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/db/config_store.py tests/db/test_config_store.py && git commit -m "feat(db): configuração no banco com validação ao salvar e ao ler" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Posições e reservas no Redis

**Files:**
- Create: `server/app/infra/__init__.py` (vazio)
- Create: `server/app/infra/redis_store.py`
- Create: `server/tests/infra/__init__.py` (vazio)
- Test: `server/tests/infra/test_redis_store.py`

**Interfaces:**
- Consumes: `GeoPoint`, `haversine_m` (plano 1); `ReservationBook` (plano 1, `app.domain.dispatch`); fixture `redis_client` (tarefa 3).
- Produces:
  - `PositionStore` (Protocol): `update(rider_id, point: GeoPoint, now: float) -> None`, `remove(rider_id) -> None`, `get(rider_id) -> GeoPoint | None`, `nearby(center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0) -> list[tuple[str, GeoPoint]]` (do mais perto para o mais longe; ignora posições mais velhas que `max_age_s`).
  - `InMemoryPositionStore()` e `RedisPositionStore(client)` implementando `PositionStore`.
  - `RedisReservationBook(client, ttl_ms: int = 30_000, prefix: str = "resv:")` com `reserve(rider_id, ride_id) -> bool` e `release(rider_id, ride_id) -> None`, igual ao `ReservationBook` do domínio, mas com validade: a reserva some sozinha depois de `ttl_ms`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/infra/test_redis_store.py`:

```python
import threading
import time

import pytest

from app.domain.dispatch import ReservationBook
from app.infra.redis_store import InMemoryPositionStore, RedisPositionStore, RedisReservationBook
from tests.helpers import ORIGIN, pt


@pytest.fixture(params=["memoria", "redis"])
def store(request, redis_client):
    if request.param == "memoria":
        return InMemoryPositionStore()
    return RedisPositionStore(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def book(request, redis_client):
    if request.param == "memoria":
        return ReservationBook()
    return RedisReservationBook(redis_client, ttl_ms=30_000)


def test_guarda_e_devolve_a_posicao(store):
    store.update("r1", pt(100, 50), now=100)
    got = store.get("r1")
    assert got.lat == pytest.approx(pt(100, 50).lat, abs=1e-5)
    assert got.lng == pytest.approx(pt(100, 50).lng, abs=1e-5)


def test_posicao_desconhecida_e_none(store):
    assert store.get("ninguem") is None


def test_busca_por_perto_ordena_pela_distancia(store):
    store.update("longe", pt(5000, 0), now=100)
    store.update("r2", pt(300, 0), now=100)
    store.update("r1", pt(100, 0), now=100)
    result = store.nearby(ORIGIN, radius_m=1000, now=100)
    assert [rider_id for rider_id, _ in result] == ["r1", "r2"]


def test_posicao_antiga_nao_conta(store):
    store.update("r1", pt(100, 0), now=100)
    assert store.nearby(ORIGIN, 1000, now=120, max_age_s=30) != []
    assert store.nearby(ORIGIN, 1000, now=200, max_age_s=30) == []


def test_remover_tira_da_busca(store):
    store.update("r1", pt(100, 0), now=100)
    store.remove("r1")
    assert store.get("r1") is None
    assert store.nearby(ORIGIN, 1000, now=100) == []


def test_atualizar_move_a_moto(store):
    store.update("r1", pt(100, 0), now=100)
    store.update("r1", pt(5000, 0), now=110)
    assert store.nearby(ORIGIN, 1000, now=110) == []


def test_reserva_e_idempotente_para_a_mesma_corrida_e_recusa_outra(book):
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-2")  # corrida errada: não libera
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-1")
    assert book.reserve("rider-1", "ride-2") is True


def test_reserva_com_pedidos_ao_mesmo_tempo_so_um_ganha(book):
    results: list[bool] = []
    lock = threading.Lock()

    def tentar(ride_id: str) -> None:
        ok = book.reserve("rider-1", ride_id)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=tentar, args=(f"ride-{i}",)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 1


def test_reserva_do_redis_expira_sozinha(redis_client):
    # Review Focus 5: se ninguém liberar a reserva, a moto não fica presa para sempre.
    book = RedisReservationBook(redis_client, ttl_ms=150)
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    time.sleep(0.3)
    assert book.reserve("rider-1", "ride-2") is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `mkdir -p app/infra tests/infra && touch app/infra/__init__.py tests/infra/__init__.py && .venv/bin/pytest tests/infra/test_redis_store.py -v`
Expected: `ModuleNotFoundError: No module named 'app.infra.redis_store'`.

- [ ] **Step 3: Implementar**

`server/app/infra/redis_store.py`:

```python
"""Posições atuais das motos e reservas de oferta, no Redis (spec, seção 10).

A posição muda a cada poucos segundos, por isso fica no Redis e não no banco principal.
"""
from __future__ import annotations

from typing import Protocol

import redis

from app.domain.geo import GeoPoint, haversine_m


class PositionStore(Protocol):
    def update(self, rider_id: str, point: GeoPoint, now: float) -> None: ...

    def remove(self, rider_id: str) -> None: ...

    def get(self, rider_id: str) -> GeoPoint | None: ...

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]: ...


class InMemoryPositionStore:
    """Versão em memória, para testes e para o simulador."""

    def __init__(self) -> None:
        self._points: dict[str, GeoPoint] = {}
        self._seen: dict[str, float] = {}

    def update(self, rider_id: str, point: GeoPoint, now: float) -> None:
        self._points[rider_id] = point
        self._seen[rider_id] = now

    def remove(self, rider_id: str) -> None:
        self._points.pop(rider_id, None)
        self._seen.pop(rider_id, None)

    def get(self, rider_id: str) -> GeoPoint | None:
        return self._points.get(rider_id)

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]:
        found = [
            (haversine_m(center, point), rider_id, point)
            for rider_id, point in self._points.items()
            if now - self._seen[rider_id] <= max_age_s
        ]
        found = [item for item in found if item[0] <= radius_m]
        found.sort(key=lambda item: item[0])
        return [(rider_id, point) for _, rider_id, point in found]


class RedisPositionStore:
    GEO = "pos:geo"
    SEEN = "pos:seen"

    def __init__(self, client: redis.Redis) -> None:
        self.r = client

    def update(self, rider_id: str, point: GeoPoint, now: float) -> None:
        pipe = self.r.pipeline()
        pipe.geoadd(self.GEO, (point.lng, point.lat, rider_id))
        pipe.zadd(self.SEEN, {rider_id: now})
        pipe.execute()

    def remove(self, rider_id: str) -> None:
        pipe = self.r.pipeline()
        pipe.zrem(self.GEO, rider_id)
        pipe.zrem(self.SEEN, rider_id)
        pipe.execute()

    def get(self, rider_id: str) -> GeoPoint | None:
        pos = self.r.geopos(self.GEO, rider_id)[0]
        if pos is None:
            return None
        return GeoPoint(lat=pos[1], lng=pos[0])

    def nearby(
        self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
    ) -> list[tuple[str, GeoPoint]]:
        found = self.r.geosearch(
            self.GEO,
            longitude=center.lng,
            latitude=center.lat,
            radius=radius_m,
            unit="m",
            sort="ASC",
            withcoord=True,
        )
        if not found:
            return []
        seen = self.r.zmscore(self.SEEN, [item[0] for item in found])
        result: list[tuple[str, GeoPoint]] = []
        for (rider_id, (lng, lat)), ts in zip(found, seen):
            if ts is not None and now - ts <= max_age_s:
                result.append((rider_id, GeoPoint(lat=lat, lng=lng)))
        return result


_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisReservationBook:
    """Reserva de uma moto para a oferta de um pedido só, com validade (`ttl_ms`)."""

    def __init__(self, client: redis.Redis, ttl_ms: int = 30_000, prefix: str = "resv:") -> None:
        self.r = client
        self.ttl_ms = ttl_ms
        self.prefix = prefix
        self._release = client.register_script(_RELEASE_LUA)

    def _key(self, rider_id: str) -> str:
        return f"{self.prefix}{rider_id}"

    def reserve(self, rider_id: str, ride_id: str) -> bool:
        key = self._key(rider_id)
        if self.r.set(key, ride_id, nx=True, px=self.ttl_ms):
            return True
        if self.r.get(key) == ride_id:
            self.r.pexpire(key, self.ttl_ms)
            return True
        return False

    def release(self, rider_id: str, ride_id: str) -> None:
        self._release(keys=[self._key(rider_id)], args=[ride_id])
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/infra/test_redis_store.py -v`
Expected: todos passam (a parametrização gera os testes duas vezes, em memória e no Redis, mais o teste de validade).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/infra tests/infra && git commit -m "feat(infra): posições das motos e reservas com validade no Redis" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Serviço transacional de pagamentos

**Files:**
- Create: `server/app/services/__init__.py` (vazio)
- Create: `server/app/services/payments.py`
- Create: `server/tests/services/__init__.py` (vazio)
- Test: `server/tests/services/test_payment_service.py`

**Interfaces:**
- Consumes: repositórios e `PgLedger` (tarefas 4 e 5); do domínio, `reserve_pix_split`, `confirm_charge_debt`, `release_charge_debt`, `restore_charge_debt`, `DebtState`, `PaymentProvider`, `PixCharge` (`app.domain.payments`); `cancel`, `CancelResult`, `cancel_unpaid_pix`, `on_pix_paid`, `pix_window_expired`, `release_from_queue`, `InvalidTransition`, `RideState` (`app.domain.rides`); `FeeConfig`, `RideConfig`; helpers de teste da tarefa 4; `FakePaymentProvider`.
- Produces: `PaymentService(provider: PaymentProvider, fee_cfg: FeeConfig | None = None, ride_cfg: RideConfig | None = None)` com (todos recebem `session` primeiro, **não fazem commit**):
  - `start_pix_charge(session, ride_id, fee_cents) -> PixCharge` (corrida Pix aceita ou na fila; reserva a dívida, cria a cobrança no provedor e grava; chamar de novo devolve a mesma cobrança)
  - `on_provider_event(session, event: dict) -> str` (`"applied"`, `"refunded"` ou `"duplicate"`)
  - `expire_unpaid_pix(session, ride_id, now) -> bool`
  - `cancel_ride(session, ride_id, now) -> CancelResult`
  - `release_queued_ride(session, ride_id, now) -> bool` (devolve se houve estorno)

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/services/test_payment_service.py`:

```python
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import DebtState
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    accept,
)
from app.domain.types import PaymentMethod
from app.services.payments import PaymentService
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider

FEE = 100


class RefundFalha(FakePaymentProvider):
    def refund(self, charge_id: str) -> None:
        raise RuntimeError("provedor fora do ar")


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def service(provider):
    return PaymentService(provider)


def mundo(session, debt=1000, busy=False, method=PaymentMethod.PIX):
    add_passenger(session)
    add_rider(session, debt_cents=debt)
    return add_accepted_ride(session, busy=busy, method=method)


def divida(session, rider_id="r1"):
    acc = repo.get_rider_account(session, rider_id)
    return acc.cash_debt_cents, acc.debt_reserved_cents


def test_cobranca_reserva_a_divida_sem_abater(session, service):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert divida(session) == (1000, 300)
    assert charge.split.debt_paid_cents == 300
    assert charge.debt_state is DebtState.RESERVED
    assert repo.get_current_charge_id(session, "ride-1") == charge.charge_id
    assert repo.get_charge(session, charge.charge_id) == charge


def test_pedir_a_cobranca_de_novo_devolve_a_mesma(session, service, provider):
    mundo(session)
    primeira = service.start_pix_charge(session, "ride-1", FEE)
    segunda = service.start_pix_charge(session, "ride-1", FEE)
    assert segunda.charge_id == primeira.charge_id
    assert len(provider.charges) == 1
    assert divida(session) == (1000, 300)


def test_so_cobra_pix_de_corrida_aceita_por_um_motoqueiro(session, service):
    mundo(session, method=PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="Pix"):
        service.start_pix_charge(session, "ride-1", FEE)
    ride = Ride("ride-2", "p1", 700, PaymentMethod.PIX, pin="4821")
    repo.add_ride(session, ride)
    with pytest.raises(InvalidTransition):
        service.start_pix_charge(session, "ride-2", FEE)


def test_pix_pago_abate_a_divida_lanca_no_livro_e_marca_a_corrida(session, service, provider):
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_ride(session, "ride-1").pix_paid is True
    assert divida(session) == (700, 0)
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300
    assert ledger.balance(PgLedger.COMPANY) == 400
    assert ledger.balance(PgLedger.PROVIDER) == -700
    assert ledger.is_balanced() is True
    salva = repo.get_charge(session, charge.charge_id)
    assert salva.paid is True and salva.debt_state is DebtState.APPLIED


def test_aviso_repetido_nao_conta_duas_vezes(session, service, provider):
    # Review Focus 1
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    event = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, event) == "applied"
    assert service.on_provider_event(session, event) == "duplicate"
    assert divida(session) == (700, 0)
    assert PgLedger(session).balance("rider:r1") == 300


def test_aviso_novo_para_cobranca_ja_paga_tambem_e_ignorado(session, service, provider):
    # Review Focus 1
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    event = provider.mark_paid(charge.charge_id)
    service.on_provider_event(session, event)
    outro_id = {**event, "event_id": "evt-outro"}
    assert service.on_provider_event(session, outro_id) == "duplicate"
    assert PgLedger(session).balance("rider:r1") == 300


def test_tipo_de_aviso_desconhecido_da_erro(session, service):
    with pytest.raises(ValueError, match="desconhecido"):
        service.on_provider_event(session, {"event_id": "e", "type": "outro", "charge_id": "ch-1"})


def test_pix_vencido_cancela_e_libera_a_reserva(session, service):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.expire_unpaid_pix(session, "ride-1", now=129) is False
    assert service.expire_unpaid_pix(session, "ride-1", now=130) is True
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert divida(session) == (1000, 0)
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED


def test_cancelar_antes_de_pagar_libera_a_reserva(session, service):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.cancel_ride(session, "ride-1", now=20) == CancelResult(0, False)
    assert divida(session) == (1000, 0)
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED


def test_cancelar_corrida_paga_devolve_o_dinheiro_e_a_divida(session, service, provider):
    # Review Focus 2
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.on_provider_event(session, provider.mark_paid(charge.charge_id))
    assert service.cancel_ride(session, "ride-1", now=20) == CancelResult(0, True)
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.balance(PgLedger.COMPANY) == 0
    assert ledger.is_balanced() is True
    assert divida(session) == (1000, 0)
    salva = repo.get_charge(session, charge.charge_id)
    assert salva.refunded is True and salva.debt_state is DebtState.RESTORED


def test_aviso_atrasado_de_corrida_cancelada_e_devolvido(session, service, provider):
    # Review Focus 1 e 2: o passageiro pagou no último segundo, mas o Pix já tinha vencido.
    mundo(session)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    service.expire_unpaid_pix(session, "ride-1", now=130)
    event = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, event) == "refunded"
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 0
    assert ledger.is_balanced() is True
    assert divida(session) == (1000, 0)
    assert repo.get_ride(session, "ride-1").pix_paid is False


def test_corrida_na_fila_paga_volta_para_a_busca_com_estorno(session, service, provider):
    mundo(session, busy=True)
    charge = service.start_pix_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert service.release_queued_ride(session, "ride-1", now=500) is True
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.SEARCHING
    assert ride.rider_id is None
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert provider.charges[charge.charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert divida(session) == (1000, 0)


def test_corrida_na_fila_sem_pagar_volta_para_a_busca_e_libera_a_reserva(session, service):
    mundo(session, busy=True)
    service.start_pix_charge(session, "ride-1", FEE)
    assert service.release_queued_ride(session, "ride-1", now=500) is False
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert divida(session) == (1000, 0)


def test_aviso_de_cobranca_antiga_nao_marca_a_corrida_atual_como_paga(session, service, provider):
    # Review Focus 1: a moto r1 saiu da corrida; o passageiro pagou a cobrança velha na última hora.
    mundo(session, busy=True)
    add_rider(session, user_id="r2", phone="+5575900000009", cpf="222.222.222-22", cnh="CNH0002", plate="BBB2B22")
    velha = service.start_pix_charge(session, "ride-1", FEE)
    service.release_queued_ride(session, "ride-1", now=500)
    ride = repo.get_ride(session, "ride-1")
    accept(ride, "r2", 510, rider_busy=False)
    repo.save_ride(session, ride)
    nova = service.start_pix_charge(session, "ride-1", FEE)
    assert nova.charge_id != velha.charge_id

    assert service.on_provider_event(session, provider.mark_paid(velha.charge_id)) == "refunded"
    assert repo.get_ride(session, "ride-1").pix_paid is False
    assert provider.charges[velha.charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert repo.get_current_charge_id(session, "ride-1") == nova.charge_id


def test_falha_do_provedor_no_estorno_nao_deixa_nada_pela_metade(session, provider):
    # Review Focus 4: o chamador desfaz a transação e tudo volta ao que era.
    servico = PaymentService(provider)
    mundo(session)
    charge = servico.start_pix_charge(session, "ride-1", FEE)
    servico.on_provider_event(session, provider.mark_paid(charge.charge_id))
    ruim = PaymentService(RefundFalha())
    with pytest.raises(RuntimeError, match="provedor"):
        with session.begin_nested():
            ruim.cancel_ride(session, "ride-1", now=20)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.ACCEPTED
    assert ride.pix_paid is True
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 300
    assert divida(session) == (700, 0)
    assert repo.get_charge(session, charge.charge_id).refunded is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `mkdir -p app/services tests/services && touch app/services/__init__.py tests/services/__init__.py && .venv/bin/pytest tests/services/test_payment_service.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.payments'`.

- [ ] **Step 3: Implementar**

`server/app/services/payments.py`:

```python
"""Fluxo de dinheiro de uma corrida Pix (spec, seções 7 e 12).

Cada método trabalha dentro da transação de quem chama: nada de `commit` aqui. Se algo falhar no
meio (por exemplo, o provedor recusar um estorno), quem chamou desfaz a transação e o livro, a dívida
e a corrida voltam ao que eram; o aviso do provedor pode então ser tratado de novo.

Ordem de travas no banco: corrida, depois motoqueiro, depois cobrança.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.config import FeeConfig, RideConfig
from app.domain.fees import RiderAccount
from app.domain.payments import (
    DebtState,
    PaymentProvider,
    PixCharge,
    confirm_charge_debt,
    release_charge_debt,
    reserve_pix_split,
    restore_charge_debt,
)
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    cancel,
    cancel_unpaid_pix,
    on_pix_paid,
    pix_window_expired,
    release_from_queue,
)
from app.domain.types import PaymentMethod


class PaymentService:
    def __init__(
        self,
        provider: PaymentProvider,
        fee_cfg: FeeConfig | None = None,
        ride_cfg: RideConfig | None = None,
    ) -> None:
        self.provider = provider
        self.fee_cfg = fee_cfg or FeeConfig()
        self.ride_cfg = ride_cfg or RideConfig()

    # --- auxiliares ---------------------------------------------------------------

    def _rider_and_charge(
        self, session: Session, ride: Ride
    ) -> tuple[RiderAccount | None, PixCharge | None]:
        if ride.rider_id is None:
            return None, None
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        charge_id = repo.get_current_charge_id(session, ride.ride_id)
        charge = repo.get_charge(session, charge_id, for_update=True) if charge_id else None
        return acc, charge

    def _refund(self, charge: PixCharge, acc: RiderAccount, ledger: PgLedger) -> None:
        """Devolve um Pix pago: provedor, livro-caixa e dívida (a reservada é solta, a abatida volta)."""
        self.provider.refund(charge.charge_id)
        ledger.post_refund(charge.charge_id)
        charge.refunded = True
        if charge.debt_state is DebtState.APPLIED:
            restore_charge_debt(acc, charge)
        elif charge.debt_state is DebtState.RESERVED:
            release_charge_debt(acc, charge)

    def _release_if_reserved(self, charge: PixCharge | None, acc: RiderAccount | None) -> None:
        if charge is not None and acc is not None and charge.debt_state is DebtState.RESERVED:
            release_charge_debt(acc, charge)

    # --- casos de uso --------------------------------------------------------------

    def start_pix_charge(self, session: Session, ride_id: str, fee_cents: int) -> PixCharge:
        """Chamado quando o motoqueiro aceita uma corrida Pix: reserva a dívida e cria a cobrança."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.payment_method is not PaymentMethod.PIX:
            raise InvalidTransition("esta corrida não é paga por Pix")
        if ride.rider_id is None or ride.state not in (RideState.QUEUED, RideState.ACCEPTED):
            raise InvalidTransition("só dá para cobrar uma corrida aceita por um motoqueiro")
        existing_id = repo.get_current_charge_id(session, ride_id)
        if existing_id is not None:
            return repo.get_charge(session, existing_id)
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        split = reserve_pix_split(acc, ride.price_cents, fee_cents, self.fee_cfg.max_debt_share)
        charge = self.provider.create_pix_charge(ride.ride_id, ride.rider_id, ride.price_cents, split)
        repo.add_charge(session, charge)
        repo.set_current_charge(session, ride_id, charge.charge_id)
        repo.save_rider_account(session, acc)
        return charge

    def on_provider_event(self, session: Session, event: dict) -> str:
        """Trata o aviso de "pago" do provedor. Devolve "applied", "refunded" ou "duplicate"."""
        if event.get("type") != "paid":
            raise ValueError(f"tipo de aviso desconhecido: {event.get('type')}")
        if not repo.first_time_event(session, event["event_id"]):
            return "duplicate"
        known = repo.get_charge(session, event["charge_id"])
        ride = repo.get_ride(session, known.ride_id, for_update=True)
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        ledger = PgLedger(session)
        ledger.post_charge_payment(charge.charge_id, charge.rider_id, charge.amount_cents, charge.split)
        is_current = repo.get_current_charge_id(session, ride.ride_id) == charge.charge_id
        refund_needed = on_pix_paid(ride) if is_current else True
        if refund_needed:
            self._refund(charge, acc, ledger)
            outcome = "refunded"
        else:
            confirm_charge_debt(acc, charge)
            outcome = "applied"
        repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        return outcome

    def expire_unpaid_pix(self, session: Session, ride_id: str, now: float) -> bool:
        """Cancela a corrida se o passageiro não pagou o Pix dentro da janela. Devolve se cancelou."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if not pix_window_expired(ride, now, self.ride_cfg):
            return False
        acc, charge = self._rider_and_charge(session, ride)
        cancel_unpaid_pix(ride)
        self._release_if_reserved(charge, acc)
        if charge is not None:
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        return True

    def cancel_ride(self, session: Session, ride_id: str, now: float) -> CancelResult:
        """Cancelamento pelo passageiro: devolve o Pix se já estava pago e solta a dívida reservada."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        result = cancel(ride, now, self.ride_cfg)
        if result.refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if result.refund_needed:
                self._refund(charge, acc, PgLedger(session))
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        return result

    def release_queued_ride(self, session: Session, ride_id: str, now: float) -> bool:
        """Tira a corrida da fila e volta para a busca. Devolve se houve estorno de Pix pago."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        acc, charge = self._rider_and_charge(session, ride)
        refund_needed = release_from_queue(ride, now)
        if refund_needed and (charge is None or acc is None):
            raise RuntimeError(f"corrida {ride_id} tem Pix pago, mas nenhuma cobrança registrada")
        if charge is not None and acc is not None:
            if refund_needed:
                self._refund(charge, acc, PgLedger(session))
            else:
                self._release_if_reserved(charge, acc)
            repo.save_charge(session, charge)
        if acc is not None:
            repo.save_rider_account(session, acc)
        repo.save_ride(session, ride)
        repo.set_current_charge(session, ride_id, None)
        return refund_needed
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_payment_service.py -v`
Expected: todos passam (15 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/services tests/services && git commit -m "feat(services): serviço transacional de pagamentos Pix com estorno e dívida segura" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Cenário de um dia de trabalho e documentação

**Files:**
- Test: `server/tests/services/test_dia_de_trabalho.py`
- Modify: `server/README.md`

**Interfaces:**
- Consumes: tudo das tarefas 1 a 8. Este teste prova que os módulos se encaixam com banco de verdade; o README documenta como rodar.

- [ ] **Step 1: Escrever o cenário**

`server/tests/services/test_dia_de_trabalho.py`:

```python
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.fees import register_completed_ride
from app.domain.rides import CancelResult
from app.domain.types import PaymentMethod
from app.services.payments import PaymentService
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider

FEE = 100


def test_dia_de_trabalho_com_dinheiro_pix_e_estorno_fecha_as_contas(session):
    provider = FakePaymentProvider()
    service = PaymentService(provider)
    add_passenger(session)
    add_rider(session)

    # 1) uma corrida em dinheiro já concluída: a taxa vira dívida do motoqueiro
    acc = repo.get_rider_account(session, "r1", for_update=True)
    register_completed_ride(acc, PaymentMethod.CASH, FEE)
    repo.save_rider_account(session, acc)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100

    # 2) uma corrida Pix de R$ 7,00: a dívida é abatida quando o Pix é pago
    add_accepted_ride(session, ride_id="ride-2", price=700)
    charge2 = service.start_pix_charge(session, "ride-2", FEE)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100  # ainda não abateu
    assert service.on_provider_event(session, provider.mark_paid(charge2.charge_id)) == "applied"
    acc = repo.get_rider_account(session, "r1", for_update=True)
    register_completed_ride(acc, PaymentMethod.PIX, FEE)
    repo.save_rider_account(session, acc)
    assert (acc.cash_debt_cents, acc.debt_reserved_cents, acc.completed_rides) == (0, 0, 2)

    # 3) uma corrida Pix de R$ 6,00, paga e depois cancelada: o dinheiro volta
    add_accepted_ride(session, ride_id="ride-3", price=600)
    charge3 = service.start_pix_charge(session, "ride-3", FEE)
    service.on_provider_event(session, provider.mark_paid(charge3.charge_id))
    assert service.cancel_ride(session, "ride-3", now=20) == CancelResult(0, True)

    # fechamento: o livro bate com o extrato do provedor e tudo soma zero
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 500
    assert ledger.balance(PgLedger.COMPANY) == 200
    assert ledger.balance(PgLedger.PROVIDER) == -700
    assert ledger.is_balanced() is True
    extrato = {
        f"charge:{c.charge_id}": c.amount_cents
        for c in provider.charges.values()
        if c.paid and not c.refunded
    }
    assert extrato == {f"charge:{charge2.charge_id}": 700}
    assert ledger.reconcile(extrato) == {}
```

- [ ] **Step 2: Rodar o cenário**

Run: `.venv/bin/pytest tests/services/test_dia_de_trabalho.py -v`
Expected: passa. (Esta tarefa não cria código novo de produção: o cenário só prova que as tarefas 2 a 8 se encaixam, e cada comportamento já foi levado de vermelho a verde na sua tarefa.)

- [ ] **Step 3: Atualizar o README**

Substituir o conteúdo de `server/README.md` por:

```markdown
# Servidor do app de corrida

Núcleo de regras (plano 1) mais banco, Redis e fluxo de dinheiro (plano 2A). Dinheiro sempre em centavos inteiros.

## Pré-requisitos

- Python 3.12, PostgreSQL 16 com PostGIS e Redis rodando (`systemctl is-active postgresql redis-server`).
- `server/.env` com `DATABASE_URL` e `REDIS_URL` (o arquivo é ignorado pelo git; nunca o envie).

## Instalar e rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8" "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" "redis>=5.0"
    .venv/bin/pytest -q

Os testes de banco criam um esquema temporário (`t_...`) no banco de desenvolvimento, aplicam as
migrações nele e o apagam no fim. Se um teste for interrompido à força, sobra um esquema `t_...`;
apague com `DROP SCHEMA "t_..." CASCADE`. O Redis dos testes é o banco número 15.

## Migrações

    .venv/bin/alembic upgrade head      # aplica no banco de desenvolvimento
    .venv/bin/alembic current           # mostra a versão atual

## Mapa do código

- `app/domain/` — regras de negócio puras (preço, taxa, dívida, divisão, livro-caixa em memória, corrida, escolha da moto, segurança).
- `app/db/` — modelos, repositórios, livro-caixa persistente (`pg_ledger.py`) e configuração no banco (`config_store.py`).
- `app/infra/redis_store.py` — posições das motos e reservas com validade.
- `app/services/payments.py` — serviço transacional de pagamentos Pix (cobrança, aviso de pago, vencimento, cancelamento, estorno).
- `app/adapters/` — provedores falsos de pagamento e mapas, para testes e simulador.
- `migrations/` — esquema do banco (Alembic).

## Regras de convivência

- Serviços e repositórios não fazem `commit`: quem chama controla a transação.
- Ordem de travas no banco: corrida, motoqueiro, cobrança.
```

- [ ] **Step 4: Rodar tudo e conferir**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam. Anotar o total no resumo final.

Run: `.venv/bin/alembic current`
Expected: `0001 (head)`

Run: `cd .. && git status --short | head`
Expected: apenas os arquivos desta tarefa; `server/.env` não aparece.

- [ ] **Step 5: Commit**

```bash
git add server/README.md server/tests/services/test_dia_de_trabalho.py && git commit -m "test: cenário de um dia de trabalho com banco real e README do servidor" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Autoavaliação (feita ao escrever o plano)

**Cobertura da spec e do plano 1:**
- Spec 10.1/10.2 (PostgreSQL com PostGIS, Redis para posição atual): Tarefas 3, 4, 7. O PostGIS está ativado no banco, mas as tabelas desta parte guardam latitude e longitude só no Redis; zonas de preço e histórico de trajeto com PostGIS entram no plano 2B quando o pedido de corrida precisar deles.
- Spec 7.2 (Pix criado ao aceitar, 120 s, estorno, dívida): Tarefa 8, sobre o domínio do plano 1.
- Spec 7.6 (livro que só acrescenta, conciliação): Tarefas 3 e 5.
- Spec 12 (aviso repetido, Pix vencido, provedor fora do ar, transação desfeita): Tarefa 8.
- Itens menores adiados no plano 1 e tratados aqui: `validate_fee_config` ao carregar a configuração (Tarefa 6), limite de abatimento validado (Tarefa 2), chave única de eventos no banco (Tarefas 3 e 4), reserva com validade (Tarefa 7), cobrança guardada na corrida (`current_charge_id`, Tarefa 4).

**Fora deste plano de propósito (plano 2B):** login, cadastro e aprovação do motoqueiro, pedido de corrida, procura e ofertas, tempo real, compensação de cancelamento no livro, o contador de corridas do dia para a faixa de taxa, a combinação do bloqueio da 11ª corrida com a fila.

**Limitação conhecida:** a chamada ao provedor de pagamento acontece dentro da transação. Com o provedor falso não há problema; com a Woovi real (plano 7) a criação da cobrança precisa usar uma chave de idempotência para que uma cobrança criada e não gravada possa ser reencontrada.

**Varredura de lacunas e nomes:** nenhum passo tem "a definir", "tratar erros depois" ou "similar à tarefa N". Os nomes usados nas tarefas seguintes (`Settings`, `load_settings`, `Base` e as `*Row`, `make_engine`, `make_session_factory`, as funções de `repositories`, `PgLedger`, `AppConfig`, `save_config`, `load_config`, `load_app_config`, `PositionStore`, `InMemoryPositionStore`, `RedisPositionStore`, `RedisReservationBook`, `PaymentService`) são os mesmos definidos nas tarefas que os produzem.
