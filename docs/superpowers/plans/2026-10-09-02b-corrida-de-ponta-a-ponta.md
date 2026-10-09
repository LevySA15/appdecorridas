# Corrida de ponta a ponta (serviços) — Plano de implementação (plano 2B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a corrida andar de ponta a ponta no servidor, sem HTTP: login por código, cadastro e aprovação do motoqueiro, preço e pedido, procura e ofertas (uma moto por vez, com fila), andamento da corrida, dinheiro do fim da corrida em dinheiro vivo (QR, bloqueio automático do passageiro que não paga e repasse ao motoqueiro quando pagar), taxa de entrada, avaliações e as varreduras de tempo.

**Architecture:** Serviços em `app/services/` sobre o banco do plano 2A e o domínio do plano 1. Cada serviço trabalha dentro da transação de quem chama e **nunca faz `commit`**. Tempo (`now`) sempre entra como parâmetro (segundos, `float`). Avisos para os apps vão para um `EventCollector` e só são publicados por quem chama, depois do commit (a publicação em si é do plano 2C). Mapas, envio de código e provedor de pagamento são interfaces com versões falsas. Ordem de travas no banco: corrida → motoqueiro → cobrança → passageiro.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, psycopg 3, Alembic, redis-py, pytest (igual ao 2A). Nenhuma biblioteca nova, exceto `tzdata` (fuso America/Bahia).

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 5, 6, 7, 8, 10.4 e 12). Este é o plano 2B de 9; ver `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`. Parte do plano 2A (`2026-10-08-02a-banco-e-dinheiro.md`) e do plano 1.

## Global Constraints

- Dinheiro sempre em **centavos inteiros** (`int`). Tempos em segundos (`float`, época Unix); datas de validade de documento em `datetime.date`.
- Serviços e repositórios **não fazem `commit`**. Ordem de travas: corrida → motoqueiro → cobrança → passageiro. Uma operação que trava duas corridas (promoção da fila) trava primeiro a que está terminando, depois a da fila.
- Um motoqueiro **nunca** tem duas corridas ativas; no máximo **1** corrida na fila; **uma** oferta pendente por vez para cada motoqueiro e para cada corrida (o banco também garante).
- Oferta dura `DispatchConfig.offer_timeout_s` (15 s); procura desiste em `RideConfig.search_give_up_s` (120 s); Pix vence em `RideConfig.pix_window_s` (120 s); fila espera no máximo `queue_max_wait_s` (480 s); espera na chegada, `max_wait_at_arrival_s` (300 s).
- **Corrida em dinheiro (decisão do Levy, 09/10/2026):** não existe botão de "passageiro não pagou". O motoqueiro espera o pagamento; passados `RideConfig.cash_pay_wait_s` (300 s) o servidor bloqueia o passageiro sozinho e o motoqueiro **não deve taxa** daquela corrida. Quando o passageiro paga (Pix, divisão normal), o valor vai para o motoqueiro daquela corrida e o bloqueio cai. O motoqueiro só deve a taxa quando o passageiro de fato pagou em dinheiro vivo e ele confirmou.
- Código de login: 6 dígitos, vale 300 s, no máximo 5 tentativas, no máximo 5 pedidos por hora por número. Sessão dura 180 dias. O código nunca é guardado em texto puro.
- Telefones guardados como `+55DDD9XXXXXXXX`. CPF guardado como `000.000.000-00`. Placa guardada em maiúsculas, sem hífen.
- Erros que o usuário vê, em português do Brasil, em frases curtas e sem culpar o usuário.
- Segredos só em `server/.env`. Os testes usam o esquema temporário `t_<aleatório>` e o Redis banco 15 (plano 2A).
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Todos os comandos partem da pasta `server/`. `systemctl is-active postgresql redis-server` deve responder `active` duas vezes.

## Review Focus

1. **Pagamento do fim da corrida em dinheiro:** Pix pelo QR dentro do prazo; motoqueiro confirma dinheiro e o QR é pago depois (deve ser devolvido); prazo vence e o passageiro é bloqueado; passageiro paga atrasado (desbloqueia, paga o motoqueiro uma vez só); motoqueiro tenta confirmar dinheiro depois do bloqueio (Tarefa 7).
2. **Duas ofertas ao mesmo tempo:** a mesma moto oferecida a dois pedidos, aceitar oferta vencida, aceitar oferta de outro motoqueiro, moto que já recusou voltar a receber o mesmo pedido (Tarefa 6).
3. **Motoqueiro que termina a 10ª corrida sem ter pagado a entrada, com uma corrida já na fila:** a corrida da fila volta para a busca e é reofertada; ele não consegue ficar disponível (Tarefa 8).
4. **Login:** código errado deve contar tentativa mesmo sem `commit` de erro, código reaproveitado, código vencido, excesso de pedidos, conta bloqueada, número que já é de outro tipo de conta (Tarefa 3).
5. **Pedido de corrida:** cotação vencida, usada duas vezes ou de outro passageiro; passageiro com corrida aberta, com pagamento pendente ou bloqueado (Tarefa 5).

---

### Task 1: Esquema novo (migração 0002 e modelos)

**Files:**
- Modify: `server/app/db/models.py`
- Create: `server/migrations/versions/0002_corrida_e_acesso.py`
- Test: `server/tests/db/test_schema_corrida.py`

**Interfaces:**
- Produces (linhas novas): `OtpCodeRow`, `SessionRow`, `QuoteRow`, `RideOfferRow`, `RideEventRow`, `RatingRow`.
- Produces (colunas novas em linhas existentes): `RideRow` (`pickup_lat`, `pickup_lng`, `dest_lat`, `dest_lng`, `pickup_text`, `dest_text`, `distance_m`, `price_factor`, `price_reason`, `fee_cents`, `completed_at`); `RiderProfileRow` (`online`, `rejected_reason`, `selfie_key`, `cnh_photo_key`, `crlv_key`, `cnh_expires_on`, `crlv_expires_on`, `rating_sum`, `rating_count`); `PixChargeRow` (`purpose`; `ride_id` passa a aceitar vazio).
- Regras no banco: uma oferta `pending` por corrida e uma por motoqueiro (índices únicos parciais); nota de 1 a 5, uma por pessoa e corrida; cobrança de finalidade `entry` pode ficar sem corrida, as outras não.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/db/test_schema_corrida.py`:

```python
import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import PixChargeRow, RatingRow, RideOfferRow, RideRow, RiderProfileRow
from tests.helpers_db import add_passenger, add_rider


def _ride(ride_id: str, passenger_id: str = "p1", state: str = "searching") -> RideRow:
    return RideRow(
        id=ride_id, passenger_id=passenger_id, price_cents=700, payment_method="pix", pin="4821", state=state
    )


def _offer(ride_id: str, rider_id: str, status: str = "pending") -> RideOfferRow:
    return RideOfferRow(
        ride_id=ride_id, rider_id=rider_id, status=status, will_queue=False, created_at=10.0, expires_at=25.0
    )


def test_so_uma_oferta_pendente_por_corrida(session):
    add_passenger(session)
    add_rider(session)
    add_rider(session, "r2", "+5575900000009", "222.222.222-22", "CNH0002", "BBB2B22")
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_offer("ride-1", "r1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-1", "r2"))
            session.flush()


def test_so_uma_oferta_pendente_por_motoqueiro(session):
    add_passenger(session)
    add_rider(session)
    session.add_all([_ride("ride-1"), _ride("ride-2")])
    session.flush()
    session.add(_offer("ride-1", "r1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-2", "r1"))
            session.flush()


def test_oferta_nova_depois_da_anterior_recusada(session):
    add_passenger(session)
    add_rider(session)
    add_rider(session, "r2", "+5575900000009", "222.222.222-22", "CNH0002", "BBB2B22")
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_offer("ride-1", "r1", status="declined"))
    session.add(_offer("ride-1", "r2", status="pending"))
    session.flush()


def test_status_de_oferta_invalido_e_recusado(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_offer("ride-1", "r1", status="talvez"))
            session.flush()


def test_nota_vai_de_1_a_5_e_e_uma_por_pessoa_e_corrida(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1", state="completed"))
    session.flush()
    for ruim in (0, 6):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=ruim, created_at=1.0))
                session.flush()
    session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=5, created_at=1.0))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(RatingRow(ride_id="ride-1", from_user="p1", to_user="r1", stars=4, created_at=2.0))
            session.flush()


def _charge(charge_id: str, ride_id: str | None, purpose: str) -> PixChargeRow:
    return PixChargeRow(
        charge_id=charge_id, ride_id=ride_id, rider_id="r1", amount_cents=5000,
        rider_cents=0, company_cents=5000, debt_paid_cents=0, purpose=purpose,
    )


def test_cobranca_de_entrada_pode_ficar_sem_corrida_mas_as_outras_nao(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    session.add(_charge("ch-entry", None, "entry"))
    session.add(_charge("ch-ride", "ride-1", "ride"))
    session.flush()
    for finalidade in ("ride", "end"):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(_charge(f"ch-{finalidade}-sem-corrida", None, finalidade))
                session.flush()


def test_finalidade_de_cobranca_invalida_e_recusada(session):
    add_passenger(session)
    add_rider(session)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_charge("ch-x", None, "outra"))
            session.flush()


def test_campos_novos_da_corrida_e_do_motoqueiro_gravam_e_voltam(session):
    add_passenger(session)
    add_rider(session)
    ride = _ride("ride-1")
    ride.pickup_lat, ride.pickup_lng = -12.9, -39.2
    ride.dest_lat, ride.dest_lng = -12.91, -39.21
    ride.pickup_text, ride.dest_text = "Rua A", "Feira livre"
    ride.distance_m, ride.price_factor, ride.price_reason = 2100, 1.1, "Preço normal"
    ride.fee_cents, ride.completed_at = 100, 99.5
    session.add(ride)
    profile = session.get(RiderProfileRow, "r1")
    profile.online = True
    profile.cnh_expires_on = dt.date(2030, 1, 1)
    profile.rating_sum, profile.rating_count = 9, 2
    session.flush()
    session.expire_all()
    assert session.get(RideRow, "ride-1").dest_text == "Feira livre"
    assert session.get(RiderProfileRow, "r1").cnh_expires_on == dt.date(2030, 1, 1)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/db/test_schema_corrida.py -q`
Expected: erro de coleta `ImportError: cannot import name 'RatingRow'`.

- [ ] **Step 3: Acrescentar os modelos**

Em `server/app/db/models.py`:

(a) trocar o bloco de importações de `sqlalchemy` para incluir `Date` e `UniqueConstraint`:

```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
```

(b) em `RiderProfileRow`, depois da linha `approved_at: ...`, acrescentar:

```python
    online: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    rejected_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    selfie_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cnh_photo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    crlv_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cnh_expires_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    crlv_expires_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    rating_sum: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
```

(c) em `RideRow`, trocar a linha `current_charge_id: ...` e a seguinte (`created_at`) por:

```python
    current_charge_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pickup_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    pickup_lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    dest_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    dest_lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    pickup_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dest_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_factor: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    price_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

(d) em `PixChargeRow`, trocar o `__table_args__` e a linha de `ride_id` e acrescentar `purpose`:

```python
    __table_args__ = (
        CheckConstraint("rider_cents + company_cents = amount_cents", name="charge_split_closes"),
        CheckConstraint("purpose IN ('ride','end','entry')", name="charge_purpose_valid"),
        CheckConstraint("purpose = 'entry' OR ride_id IS NOT NULL", name="charge_ride_required"),
    )

    charge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ride_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("rides.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(8), default="ride", server_default="ride")
```

(a linha `charge_id` já existe; o objetivo é só que `ride_id` fique opcional, `purpose` exista e as duas restrições novas entrem.)

(e) no fim do arquivo, acrescentar:

```python
class OtpCodeRow(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class SessionRow(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    device: Mapped[str] = mapped_column(String(80), default="", server_default="")
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class QuoteRow(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    pickup_lat: Mapped[float] = mapped_column(Float(53))
    pickup_lng: Mapped[float] = mapped_column(Float(53))
    dest_lat: Mapped[float] = mapped_column(Float(53))
    dest_lng: Mapped[float] = mapped_column(Float(53))
    pickup_text: Mapped[str] = mapped_column(String(200), default="", server_default="")
    dest_text: Mapped[str] = mapped_column(String(200), default="", server_default="")
    distance_m: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    factor: Mapped[float] = mapped_column(Float(53))
    reason: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class RideOfferRow(Base):
    __tablename__ = "ride_offers"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired')", name="offer_status_valid"),
        Index("offer_one_pending_per_ride", "ride_id", unique=True, postgresql_where=text("status = 'pending'")),
        Index("offer_one_pending_per_rider", "rider_id", unique=True, postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    will_queue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[float] = mapped_column(Float(53))
    expires_at: Mapped[float] = mapped_column(Float(53))


class RideEventRow(Base):
    __tablename__ = "ride_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[float] = mapped_column(Float(53))


class RatingRow(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint("stars BETWEEN 1 AND 5", name="rating_range"),
        UniqueConstraint("ride_id", "from_user", name="rating_once"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
    from_user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    to_user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    stars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float(53))
```

- [ ] **Step 4: Escrever a migração**

`server/migrations/versions/0002_corrida_e_acesso.py`:

```python
"""corrida e acesso: login, sessões, cotações, ofertas, eventos, avaliações e campos novos

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _false() -> sa.TextClause:
    return sa.text("false")


def upgrade() -> None:
    # --- colunas novas ---------------------------------------------------------
    for name, type_ in (
        ("pickup_lat", sa.Float(53)), ("pickup_lng", sa.Float(53)),
        ("dest_lat", sa.Float(53)), ("dest_lng", sa.Float(53)),
        ("pickup_text", sa.String(200)), ("dest_text", sa.String(200)),
        ("distance_m", sa.Integer()), ("price_factor", sa.Float(53)), ("price_reason", sa.String(80)),
        ("fee_cents", sa.Integer()), ("completed_at", sa.Float(53)),
    ):
        op.add_column("rides", sa.Column(name, type_, nullable=True))

    op.add_column("rider_profiles", sa.Column("online", sa.Boolean(), nullable=False, server_default=_false()))
    for name, type_ in (
        ("rejected_reason", sa.String(200)), ("selfie_key", sa.String(200)),
        ("cnh_photo_key", sa.String(200)), ("crlv_key", sa.String(200)),
        ("cnh_expires_on", sa.Date()), ("crlv_expires_on", sa.Date()),
    ):
        op.add_column("rider_profiles", sa.Column(name, type_, nullable=True))
    op.add_column("rider_profiles", sa.Column("rating_sum", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("rider_profiles", sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    op.alter_column("pix_charges", "ride_id", existing_type=sa.String(40), nullable=True)
    op.add_column("pix_charges", sa.Column("purpose", sa.String(8), nullable=False, server_default="ride"))
    op.create_check_constraint("charge_purpose_valid", "pix_charges", "purpose IN ('ride','end','entry')")
    op.create_check_constraint("charge_ride_required", "pix_charges", "purpose = 'entry' OR ride_id IS NOT NULL")

    # --- tabelas novas ---------------------------------------------------------
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=_false()),
    )
    op.create_index("ix_otp_codes_phone", "otp_codes", ["phone"])

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=_false()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("passenger_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pickup_lat", sa.Float(53), nullable=False),
        sa.Column("pickup_lng", sa.Float(53), nullable=False),
        sa.Column("dest_lat", sa.Float(53), nullable=False),
        sa.Column("dest_lng", sa.Float(53), nullable=False),
        sa.Column("pickup_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("dest_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("factor", sa.Float(53), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=_false()),
    )

    op.create_table(
        "ride_offers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("rider_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("will_queue", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("expires_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("status IN ('pending','accepted','declined','expired')", name="offer_status_valid"),
    )
    op.create_index(
        "offer_one_pending_per_ride", "ride_offers", ["ride_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "offer_one_pending_per_rider", "ride_offers", ["rider_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "ride_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.Float(53), nullable=False),
    )
    op.create_index("ix_ride_events_ride_id", "ride_events", ["ride_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("from_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name="rating_range"),
        sa.UniqueConstraint("ride_id", "from_user", name="rating_once"),
    )


def downgrade() -> None:
    op.drop_table("ratings")
    op.drop_table("ride_events")
    op.drop_table("ride_offers")
    op.drop_table("quotes")
    op.drop_table("sessions")
    op.drop_table("otp_codes")
    op.drop_constraint("charge_ride_required", "pix_charges")
    op.drop_constraint("charge_purpose_valid", "pix_charges")
    op.drop_column("pix_charges", "purpose")
    op.alter_column("pix_charges", "ride_id", existing_type=sa.String(40), nullable=False)
    for name in (
        "rating_count", "rating_sum", "crlv_expires_on", "cnh_expires_on", "crlv_key",
        "cnh_photo_key", "selfie_key", "rejected_reason", "online",
    ):
        op.drop_column("rider_profiles", name)
    for name in (
        "completed_at", "fee_cents", "price_reason", "price_factor", "distance_m", "dest_text",
        "pickup_text", "dest_lng", "dest_lat", "pickup_lng", "pickup_lat",
    ):
        op.drop_column("rides", name)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/bin/pytest tests/db/test_schema_corrida.py tests/db/test_schema.py -v`
Expected: todos passam (8 novos e os 9 do esquema do plano 2A, incluindo a conferência de tabelas e colunas entre migração e modelos).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam (220 do plano 2A mais os 8 novos).

- [ ] **Step 6: Aplicar a migração no banco de desenvolvimento**

Run: `.venv/bin/alembic upgrade head && .venv/bin/alembic current`
Expected: termina com `0002 (head)`.

- [ ] **Step 7: Commit**

```bash
git add app/db/models.py migrations/versions/0002_corrida_e_acesso.py tests/db/test_schema_corrida.py && git commit -m "feat(db): migração 0002 com login, cotações, ofertas, eventos, avaliações e campos da corrida" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Ajustes no domínio, na configuração e nos repositórios

**Files:**
- Modify: `server/pyproject.toml`
- Create: `server/app/domain/clock.py`, `server/app/domain/money.py`
- Modify: `server/app/domain/config.py`, `server/app/domain/rides.py`, `server/app/domain/fees.py`, `server/app/domain/payments.py`
- Modify: `server/app/adapters/fake_payments.py`, `server/app/db/repositories.py`, `server/app/db/config_store.py`
- Test: `server/tests/domain/test_clock.py`, `server/tests/domain/test_money.py`, `server/tests/domain/test_corrida_dinheiro.py`, `server/tests/db/test_repositories_corrida.py`, `server/tests/db/test_config_store.py` (acrescentar no fim)

**Interfaces:**
- Produces:
  - `local_date(epoch_s: float) -> date` e `local_day_start(epoch_s: float) -> float` (fuso `America/Bahia`).
  - `brl(cents: int) -> str` (`700` → `"R$ 7,00"`).
  - `RideConfig.cash_pay_wait_s = 300`, `RideConfig.quote_ttl_s = 300`; `DispatchConfig.search_radius_m = 3000.0`, `DispatchConfig.position_max_age_s = 30.0`; `AuthConfig(otp_digits=6, otp_ttl_s=300, otp_max_attempts=5, otp_requests_per_hour=5, session_days=180)`; `AppConfig.auth` (com padrão).
  - `Ride.completed_at: float | None`, `Ride.fee_cents: int | None`; `complete(ride, now=None)`.
  - `cash_pay_wait_expired(ride, now, cfg) -> bool`, `block_for_unpaid(ride, acc, now, cfg) -> None`, `confirm_qr_payment(ride) -> None` (em `app.domain.rides`).
  - `count_completed_ride(acc)` e `add_cash_fee_debt(acc, fee_cents)` (em `app.domain.fees`).
  - `PixCharge.purpose: str = "ride"` (`"ride"`, `"end"` ou `"entry"`); `PaymentProvider.create_pix_charge(ride_id, rider_id, amount_cents, split, purpose="ride")`.
  - Repositórios gravam e leem `completed_at`, `fee_cents` e `purpose` (cobrança de entrada tem `ride_id == ""` no domínio e `NULL` no banco).

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_clock.py`:

```python
from datetime import date, datetime, timezone

from app.domain.clock import local_date, local_day_start


def test_dia_local_e_o_da_bahia():
    # 02:30 UTC do dia 9 ainda é 23:30 do dia 8 na Bahia (UTC-3).
    t = datetime(2026, 10, 9, 2, 30, tzinfo=timezone.utc).timestamp()
    assert local_date(t) == date(2026, 10, 8)


def test_inicio_do_dia_local():
    t = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc).timestamp()
    assert local_day_start(t) == datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc).timestamp()
```

`server/tests/domain/test_money.py`:

```python
import pytest

from app.domain.money import brl


@pytest.mark.parametrize(
    "cents, texto",
    [(700, "R$ 7,00"), (5000, "R$ 50,00"), (5, "R$ 0,05"), (123456, "R$ 1234,56"), (0, "R$ 0,00")],
)
def test_formata_reais(cents, texto):
    assert brl(cents) == texto


def test_valor_negativo_e_recusado():
    with pytest.raises(ValueError):
        brl(-1)
```

`server/tests/domain/test_corrida_dinheiro.py`:

```python
import pytest

from app.domain.config import RideConfig
from app.domain.fees import RiderAccount, add_cash_fee_debt, count_completed_ride
from app.domain.rides import (
    InvalidTransition,
    PassengerAccount,
    Ride,
    RideState,
    accept,
    block_for_unpaid,
    cash_pay_wait_expired,
    complete,
    confirm_end_payment,
    confirm_helmet,
    confirm_qr_payment,
    mark_arrived,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod


def _concluida(method=PaymentMethod.CASH, now=1000.0) -> Ride:
    ride = Ride("ride-1", "p1", 700, method, pin="4821")
    start_search(ride, 0)
    accept(ride, "r1", 1, rider_busy=False)
    mark_arrived(ride, 2)
    confirm_helmet(ride)
    if method is PaymentMethod.PIX:
        ride.pix_paid = True
    start_ride(ride, "4821")
    complete(ride, now)
    return ride


def test_completar_guarda_o_instante():
    assert _concluida(now=1234.5).completed_at == 1234.5
    ride = Ride("r", "p", 700, PaymentMethod.CASH, pin="4821", state=RideState.IN_PROGRESS)
    complete(ride)  # sem instante continua valendo
    assert ride.completed_at is None


def test_prazo_de_pagamento_em_dinheiro():
    ride = _concluida()
    cfg = RideConfig(cash_pay_wait_s=300)
    assert cash_pay_wait_expired(ride, 1299, cfg) is False
    assert cash_pay_wait_expired(ride, 1300, cfg) is True


def test_prazo_nao_vale_para_pix_nem_para_corrida_ja_paga_ou_ja_bloqueada():
    assert cash_pay_wait_expired(_concluida(PaymentMethod.PIX), 9999) is False
    paga = _concluida()
    confirm_end_payment(paga)
    assert cash_pay_wait_expired(paga, 9999) is False
    bloqueada = _concluida()
    block_for_unpaid(bloqueada, PassengerAccount("p1"), 1300)
    assert cash_pay_wait_expired(bloqueada, 9999) is False


def test_bloqueio_por_falta_de_pagamento_soma_a_divida_do_passageiro():
    ride = _concluida()
    passenger = PassengerAccount("p1")
    block_for_unpaid(ride, passenger, 1300)
    assert passenger.unpaid_cents == 700
    assert ride.non_payment_reported is True
    with pytest.raises(InvalidTransition):
        block_for_unpaid(ride, passenger, 1400)  # só uma vez


def test_bloqueio_antes_do_prazo_e_recusado():
    with pytest.raises(InvalidTransition, match="prazo"):
        block_for_unpaid(_concluida(), PassengerAccount("p1"), 1100)


def test_pagamento_pelo_qr_confirma_a_corrida_mesmo_depois_do_bloqueio():
    ride = _concluida()
    block_for_unpaid(ride, PassengerAccount("p1"), 1300)
    confirm_qr_payment(ride)
    assert ride.end_payment_confirmed is True
    with pytest.raises(InvalidTransition, match="já foi confirmado"):
        confirm_qr_payment(ride)


def test_pagamento_pelo_qr_so_vale_para_corrida_concluida_em_dinheiro():
    with pytest.raises(InvalidTransition):
        confirm_qr_payment(_concluida(PaymentMethod.PIX))
    andando = Ride("r", "p", 700, PaymentMethod.CASH, pin="4821", state=RideState.IN_PROGRESS)
    with pytest.raises(InvalidTransition):
        confirm_qr_payment(andando)


def test_contar_corrida_e_somar_taxa_de_dinheiro_sao_passos_separados():
    acc = RiderAccount("r1")
    count_completed_ride(acc)
    assert (acc.completed_rides, acc.cash_debt_cents) == (1, 0)
    add_cash_fee_debt(acc, 100)
    assert (acc.completed_rides, acc.cash_debt_cents) == (1, 100)
    with pytest.raises(ValueError):
        add_cash_fee_debt(acc, -1)
```

`server/tests/db/test_repositories_corrida.py`:

```python
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.payments import Split
from app.domain.rides import complete, confirm_helmet, mark_arrived, start_ride
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_corrida_guarda_instante_de_conclusao_e_taxa(session):
    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session)
    ride.fee_cents = 90
    mark_arrived(ride, 20)
    confirm_helmet(ride)
    ride.pix_paid = True
    start_ride(ride, "4821")
    complete(ride, 321.5)
    repo.save_ride(session, ride)
    session.expire_all()
    carregada = repo.get_ride(session, "ride-1")
    assert (carregada.completed_at, carregada.fee_cents) == (321.5, 90)
    assert carregada == ride


def test_cobranca_de_entrada_nao_tem_corrida_e_volta_igual(session):
    add_rider(session)
    charge = FakePaymentProvider().create_pix_charge("", "r1", 5000, Split(0, 5000, 0), purpose="entry")
    assert charge.purpose == "entry" and charge.ride_id == ""
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id) == charge


def test_cobranca_de_fim_de_corrida_guarda_a_finalidade(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, Split(600, 100, 0), purpose="end")
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id).purpose == "end"
```

Acrescentar ao fim de `server/tests/db/test_config_store.py`:

```python
def test_configuracao_de_login_vai_e_volta(session):
    from app.domain.config import AuthConfig

    custom = AuthConfig(otp_digits=4, otp_ttl_s=60, otp_max_attempts=3, otp_requests_per_hour=2, session_days=30)
    save_config(session, "auth", custom)
    session.expire_all()
    assert load_config(session, "auth") == custom
    assert load_app_config(session).auth == custom
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_clock.py tests/domain/test_money.py tests/domain/test_corrida_dinheiro.py tests/db/test_repositories_corrida.py tests/db/test_config_store.py -q 2>&1 | tail -15`
Expected: erros de coleta (`ModuleNotFoundError: app.domain.clock` e semelhantes) e falha de importação de `AuthConfig`.

- [ ] **Step 3: Implementar**

Em `server/pyproject.toml`, na lista `dependencies`, acrescentar `"tzdata>=2024.1",` e rodar `.venv/bin/pip install -q "tzdata>=2024.1"`.

`server/app/domain/clock.py`:

```python
"""Dia local da operação (Bahia, UTC-3, sem horário de verão). Usado para contar as corridas do dia."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Bahia")


def local_date(epoch_s: float) -> date:
    return datetime.fromtimestamp(epoch_s, LOCAL_TZ).date()


def local_day_start(epoch_s: float) -> float:
    d = local_date(epoch_s)
    return datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ).timestamp()
```

`server/app/domain/money.py`:

```python
"""Formatação de dinheiro para textos que o usuário lê."""
from __future__ import annotations


def brl(cents: int) -> str:
    if cents < 0:
        raise ValueError("o valor não pode ser negativo")
    return f"R$ {cents // 100},{cents % 100:02d}"
```

Em `server/app/domain/config.py`:

- na `RideConfig`, depois de `search_give_up_s: int = 120`, acrescentar:

```python
    cash_pay_wait_s: int = 300      # espera pelo pagamento do fim da corrida em dinheiro
    quote_ttl_s: int = 300          # validade do preço mostrado antes do pedido
```

- na `DispatchConfig`, depois de `finishing_max_m: int = 500`, acrescentar:

```python
    search_radius_m: float = 3000.0     # só motos até essa distância em linha reta recebem oferta
    position_max_age_s: float = 30.0    # posição mais velha que isso não conta
```

- no fim do arquivo, acrescentar:

```python


@dataclass(frozen=True)
class AuthConfig:
    otp_digits: int = 6
    otp_ttl_s: int = 300
    otp_max_attempts: int = 5
    otp_requests_per_hour: int = 5
    session_days: int = 180
```

Em `server/app/domain/rides.py`:

- no `@dataclass class Ride`, depois de `non_payment_reported: bool = False`, acrescentar:

```python
    completed_at: float | None = None
    fee_cents: int | None = None        # taxa por corrida decidida quando o motoqueiro aceitou
```

- trocar a função `complete` por:

```python
def complete(ride: Ride, now: float | None = None) -> None:
    _require(ride, RideState.IN_PROGRESS)
    ride.state = RideState.COMPLETED
    ride.completed_at = now
```

- no fim do arquivo, acrescentar (depois de `settle_passenger_debt`):

```python


def cash_pay_wait_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    """A corrida em dinheiro acabou, ninguém pagou, e o prazo de espera passou."""
    if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
        return False
    if ride.end_payment_confirmed or ride.non_payment_reported or ride.completed_at is None:
        return False
    return now - ride.completed_at >= cfg.cash_pay_wait_s


def block_for_unpaid(ride: Ride, acc: PassengerAccount, now: float, cfg: RideConfig = _DEFAULT) -> None:
    """Passou o prazo sem pagamento: o passageiro fica devendo e bloqueado para novos pedidos.

    É automático (decisão do Levy, 09/10/2026): o motoqueiro não tem botão de "não pagou".
    """
    if not cash_pay_wait_expired(ride, now, cfg):
        raise InvalidTransition("o prazo de pagamento ainda não acabou")
    ride.non_payment_reported = True
    acc.unpaid_cents += ride.price_cents


def confirm_qr_payment(ride: Ride) -> None:
    """O Pix do QR do fim da corrida foi pago (dentro do prazo ou depois do bloqueio)."""
    _require(ride, RideState.COMPLETED)
    if ride.payment_method is not PaymentMethod.CASH:
        raise InvalidTransition("esta corrida foi paga por Pix antes de começar")
    if ride.end_payment_confirmed:
        raise InvalidTransition("o pagamento desta corrida já foi confirmado")
    ride.end_payment_confirmed = True
```

Em `server/app/domain/fees.py`, no fim do arquivo, acrescentar:

```python


def count_completed_ride(acc: RiderAccount) -> None:
    """Conta a corrida concluída, sem mexer na dívida (a taxa em dinheiro vivo é somada à parte)."""
    acc.completed_rides += 1


def add_cash_fee_debt(acc: RiderAccount, fee_cents: int) -> None:
    """O passageiro pagou em dinheiro vivo e o motoqueiro confirmou: a taxa vira dívida dele."""
    if fee_cents < 0:
        raise ValueError("a taxa não pode ser negativa")
    acc.cash_debt_cents += fee_cents
```

Em `server/app/domain/payments.py`:

- na classe `PixCharge`, depois de `debt_state: DebtState = DebtState.RESERVED`, acrescentar:

```python
    purpose: str = "ride"   # "ride" (Pix antes da corrida), "end" (QR do fim em dinheiro) ou "entry" (entrada de R$ 50)
```

- trocar o método do `PaymentProvider` por:

```python
    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split, purpose: str = "ride"
    ) -> PixCharge: ...
```

Em `server/app/adapters/fake_payments.py`, trocar a assinatura e a construção de `create_pix_charge` por:

```python
    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split, purpose: str = "ride"
    ) -> PixCharge:
        if split.rider_cents + split.company_cents != amount_cents:
            raise ValueError("a divisão não fecha com o valor da cobrança")
        self._counter += 1
        charge = PixCharge(
            charge_id=f"ch-{self._counter}",
            ride_id=ride_id,
            rider_id=rider_id,
            amount_cents=amount_cents,
            split=split,
            purpose=purpose,
        )
        self.charges[charge.charge_id] = charge
        return charge
```

Em `server/app/db/repositories.py`:

- em `_ride_to_domain`, depois de `non_payment_reported=row.non_payment_reported,`, acrescentar `completed_at=row.completed_at,` e `fee_cents=row.fee_cents,`;
- em `_apply_ride`, depois de `row.non_payment_reported = ride.non_payment_reported`, acrescentar `row.completed_at = ride.completed_at` e `row.fee_cents = ride.fee_cents`;
- em `_charge_to_domain`, trocar `ride_id=row.ride_id,` por `ride_id=row.ride_id or "",` e, depois de `debt_state=DebtState(row.debt_state),`, acrescentar `purpose=row.purpose,`;
- em `_apply_charge`, trocar `row.ride_id = charge.ride_id` por `row.ride_id = charge.ride_id or None` e, depois de `row.debt_state = charge.debt_state.value`, acrescentar `row.purpose = charge.purpose`.

Em `server/app/db/config_store.py`:

- acrescentar `AuthConfig,` à lista importada de `app.domain.config`;
- em `_TYPES`, acrescentar `"auth": AuthConfig,`;
- na classe `AppConfig`, depois de `safety: SafetyConfig`, acrescentar `auth: AuthConfig = AuthConfig()`;
- em `load_app_config`, depois de `safety=load_config(session, "safety"),`, acrescentar `auth=load_config(session, "auth"),`.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain tests/db -q 2>&1 | tail -5`
Expected: todos passam.

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam (nada do plano 1 nem do 2A quebra).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/domain app/adapters app/db tests && git commit -m "feat(domain): prazo de pagamento em dinheiro, finalidade da cobrança, dia local e configuração de login" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Avisos e login por código

**Files:**
- Create: `server/app/services/events.py`, `server/app/services/auth.py`, `server/app/adapters/fake_otp.py`
- Test: `server/tests/services/test_events.py`, `server/tests/services/test_auth.py`

**Interfaces:**
- Consumes: `repositories.add_user`, `add_passenger_profile`; `UserRow`, `OtpCodeRow`, `SessionRow`; `AuthConfig`.
- Produces:
  - `Event(user_id: str, type: str, payload: dict)` e `EventCollector` com `add(user_id, type, payload=None)`, `drain() -> list[Event]` e a propriedade `events`.
  - `OtpSender` (Protocol: `send(phone, code)`); `FakeOtpSender` com `sent: list[tuple[str, str]]` e `last_code(phone)`.
  - `normalize_phone(raw) -> str`; `TooManyRequests`; `LoginResult(ok, reason=None, token=None, user_id=None, role=None, is_new_user=False)`; `AuthUser(user_id, phone, name, role)`.
  - `AuthService(sender, cfg=None)` com `request_code(session, raw_phone, now)`, `verify_code(session, raw_phone, code, role, device, now) -> LoginResult` (**nunca levanta por código errado**: devolve `ok=False`, para o chamador poder gravar a tentativa), `authenticate(session, token, now) -> AuthUser | None`, `logout(session, token)`, `set_name(session, user_id, name)`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/services/test_events.py`:

```python
from app.services.events import Event, EventCollector


def test_coletor_guarda_e_entrega_na_ordem_uma_vez_so():
    coletor = EventCollector()
    coletor.add("u1", "oferta", {"ride_id": "ride-1"})
    coletor.add("u2", "aceita")
    assert coletor.events == (Event("u1", "oferta", {"ride_id": "ride-1"}), Event("u2", "aceita", {}))
    assert [e.type for e in coletor.drain()] == ["oferta", "aceita"]
    assert coletor.drain() == []
```

`server/tests/services/test_auth.py`:

```python
import pytest
from sqlalchemy import select

from app.adapters.fake_otp import FakeOtpSender
from app.db import repositories as repo
from app.db.models import OtpCodeRow, UserRow
from app.domain.config import AuthConfig
from app.services.auth import AuthService, TooManyRequests, normalize_phone

PHONE = "75 99999-1234"
NORMAL = "+5575999991234"


@pytest.fixture()
def sender():
    return FakeOtpSender()


@pytest.fixture()
def auth(sender):
    return AuthService(sender)


def _login(auth, sender, session, now=1000.0, role="passenger", device="Moto G"):
    auth.request_code(session, PHONE, now)
    return auth.verify_code(session, PHONE, sender.last_code(NORMAL), role, device, now + 5)


@pytest.mark.parametrize(
    "bruto",
    ["75 99999-1234", "(75) 99999-1234", "+55 75 99999-1234", "5575999991234", "75999991234"],
)
def test_telefones_validos_viram_o_mesmo_numero(bruto):
    assert normalize_phone(bruto) == NORMAL


@pytest.mark.parametrize("bruto", ["", "abc", "9999-1234", "7533211234", "75 89999-1234", "+1 415 555 0100"])
def test_telefones_invalidos_sao_recusados(bruto):
    with pytest.raises(ValueError):
        normalize_phone(bruto)


def test_pedir_codigo_envia_pelo_canal_e_nao_guarda_o_codigo_puro(auth, sender, session):
    auth.request_code(session, PHONE, 1000.0)
    phone, code = sender.sent[-1]
    assert phone == NORMAL and len(code) == 6 and code.isdigit()
    row = session.execute(select(OtpCodeRow)).scalar_one()
    assert code not in row.code_hash and row.code_hash != code


def test_primeiro_login_cria_passageiro_com_perfil_e_sessao(auth, sender, session):
    result = _login(auth, sender, session)
    assert result.ok and result.is_new_user and result.role == "passenger"
    user = auth.authenticate(session, result.token, 1100.0)
    assert (user.user_id, user.phone, user.role) == (result.user_id, NORMAL, "passenger")
    assert repo.get_passenger_account(session, result.user_id).unpaid_cents == 0


def test_segundo_login_reaproveita_o_usuario_com_outro_token(auth, sender, session):
    primeiro = _login(auth, sender, session)
    segundo = _login(auth, sender, session, now=5000.0, device="Outro celular")
    assert segundo.ok and not segundo.is_new_user
    assert segundo.user_id == primeiro.user_id and segundo.token != primeiro.token


def test_codigo_errado_conta_tentativa_sem_levantar_erro(auth, sender, session):
    # Review Focus 4: o chamador faz commit porque nada foi levantado, então a tentativa fica gravada.
    auth.request_code(session, PHONE, 1000.0)
    resultado = auth.verify_code(session, PHONE, "000000", "passenger", "x", 1001.0)
    assert resultado.ok is False and "errado" in resultado.reason
    session.expire_all()
    assert session.execute(select(OtpCodeRow.attempts)).scalar_one() == 1


def test_depois_de_5_erros_nem_o_codigo_certo_vale(auth, sender, session):
    auth.request_code(session, PHONE, 1000.0)
    certo = sender.last_code(NORMAL)
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):
        assert auth.verify_code(session, PHONE, errado, "passenger", "x", 1001.0).ok is False
    resultado = auth.verify_code(session, PHONE, certo, "passenger", "x", 1002.0)
    assert resultado.ok is False and "tentativas" in resultado.reason


def test_codigo_vencido_e_codigo_reaproveitado_nao_valem(auth, sender, session):
    auth.request_code(session, PHONE, 1000.0)
    code = sender.last_code(NORMAL)
    assert auth.verify_code(session, PHONE, code, "passenger", "x", 1000.0 + 301).ok is False
    auth.request_code(session, PHONE, 2000.0)
    code = sender.last_code(NORMAL)
    assert auth.verify_code(session, PHONE, code, "passenger", "x", 2001.0).ok is True
    assert auth.verify_code(session, PHONE, code, "passenger", "x", 2002.0).ok is False


def test_limite_de_pedidos_de_codigo_por_hora(auth, sender, session):
    for i in range(5):
        auth.request_code(session, PHONE, 1000.0 + i)
    with pytest.raises(TooManyRequests):
        auth.request_code(session, PHONE, 1010.0)
    auth.request_code(session, PHONE, 1000.0 + 3601)  # passou uma hora


def test_limites_vem_da_configuracao(sender, session):
    auth = AuthService(sender, AuthConfig(otp_digits=4, otp_requests_per_hour=1))
    auth.request_code(session, PHONE, 1000.0)
    assert len(sender.last_code(NORMAL)) == 4
    with pytest.raises(TooManyRequests):
        auth.request_code(session, PHONE, 1001.0)


def test_numero_que_ja_e_de_outro_tipo_de_conta_nao_entra(auth, sender, session):
    _login(auth, sender, session, role="passenger")
    resultado = _login(auth, sender, session, now=5000.0, role="rider")
    assert resultado.ok is False and "passageiro" in resultado.reason


def test_conta_bloqueada_nao_entra_e_sessao_antiga_para_de_valer(auth, sender, session):
    entrou = _login(auth, sender, session)
    session.get(UserRow, entrou.user_id).is_blocked = True
    session.flush()
    assert auth.authenticate(session, entrou.token, 1100.0) is None
    resultado = _login(auth, sender, session, now=5000.0)
    assert resultado.ok is False and "bloqueada" in resultado.reason


def test_sair_encerra_a_sessao_e_sessao_longa_vence_em_180_dias(auth, sender, session):
    entrou = _login(auth, sender, session)
    assert auth.authenticate(session, entrou.token, 1000.0 + 179 * 86400) is not None
    assert auth.authenticate(session, entrou.token, 1000.0 + 181 * 86400) is None
    auth.logout(session, entrou.token)
    assert auth.authenticate(session, entrou.token, 1100.0) is None
    assert auth.authenticate(session, "token-inventado", 1100.0) is None


def test_nome_do_usuario(auth, sender, session):
    entrou = _login(auth, sender, session)
    auth.set_name(session, entrou.user_id, "  Ana Lima ")
    assert auth.authenticate(session, entrou.token, 1100.0).name == "Ana Lima"
    with pytest.raises(ValueError, match="nome"):
        auth.set_name(session, entrou.user_id, " ")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_events.py tests/services/test_auth.py -q 2>&1 | tail -6`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.services.events'`.

- [ ] **Step 3: Implementar**

`server/app/services/events.py`:

```python
"""Avisos para os apps. Os serviços só anotam; quem chama publica depois do commit (plano 2C)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    user_id: str
    type: str
    payload: dict = field(default_factory=dict)


class EventCollector:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def add(self, user_id: str, type: str, payload: dict | None = None) -> None:
        self._events.append(Event(user_id, type, payload or {}))

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def drain(self) -> list[Event]:
        events, self._events = self._events, []
        return events
```

`server/app/adapters/fake_otp.py`:

```python
"""Envio de código falso, para testes e para o simulador. Guarda o que "enviou"."""
from __future__ import annotations


class FakeOtpSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))

    def last_code(self, phone: str) -> str:
        return next(code for p, code in reversed(self.sent) if p == phone)
```

`server/app/services/auth.py`:

```python
"""Login por código no WhatsApp e sessões longas (spec, seção 10.4).

`verify_code` não levanta erro quando o código está errado: devolve `ok=False`. Assim o chamador
faz `commit` e a tentativa errada fica gravada (se levantasse, o `rollback` apagaria a contagem).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import OtpCodeRow, SessionRow, UserRow
from app.domain.config import AuthConfig

_ROLE_NAMES = {"passenger": "passageiro", "rider": "motoqueiro", "admin": "administrador"}


class OtpSender(Protocol):
    def send(self, phone: str, code: str) -> None: ...


class TooManyRequests(Exception):
    """Pediu código demais para o mesmo número."""


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    reason: str | None = None
    token: str | None = None
    user_id: str | None = None
    role: str | None = None
    is_new_user: bool = False


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    phone: str
    name: str
    role: str


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) == 10:
        raise ValueError("O celular precisa ter o 9 na frente do número.")
    if len(digits) != 11 or digits[2] != "9":
        raise ValueError("Número de celular inválido.")
    return "+55" + digits


def _hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, sender: OtpSender, cfg: AuthConfig | None = None) -> None:
        self.sender = sender
        self.cfg = cfg or AuthConfig()

    def request_code(self, session: Session, raw_phone: str, now: float) -> None:
        phone = normalize_phone(raw_phone)
        recent = session.execute(
            select(func.count()).select_from(OtpCodeRow).where(
                OtpCodeRow.phone == phone, OtpCodeRow.created_at > now - 3600
            )
        ).scalar_one()
        if recent >= self.cfg.otp_requests_per_hour:
            raise TooManyRequests("Muitos pedidos de código. Tente de novo mais tarde.")
        digits = self.cfg.otp_digits
        code = f"{secrets.randbelow(10 ** digits):0{digits}d}"
        session.add(
            OtpCodeRow(
                phone=phone, code_hash=_hash(phone, code), created_at=now, expires_at=now + self.cfg.otp_ttl_s
            )
        )
        session.flush()
        self.sender.send(phone, code)

    def verify_code(
        self, session: Session, raw_phone: str, code: str, role: str, device: str, now: float
    ) -> LoginResult:
        if role not in ("passenger", "rider"):
            raise ValueError("papel inválido")
        phone = normalize_phone(raw_phone)
        row = session.execute(
            select(OtpCodeRow)
            .where(OtpCodeRow.phone == phone, OtpCodeRow.used.is_(False))
            .order_by(OtpCodeRow.id.desc())
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or now > row.expires_at:
            return LoginResult(False, reason="Código vencido. Peça um novo.")
        if row.attempts >= self.cfg.otp_max_attempts:
            return LoginResult(False, reason="Muitas tentativas. Peça um novo código.")
        if not hmac.compare_digest(row.code_hash, _hash(phone, code.strip())):
            row.attempts += 1
            session.flush()
            return LoginResult(False, reason="Código errado.")
        user = session.execute(select(UserRow).where(UserRow.phone == phone)).scalar_one_or_none()
        if user is not None and user.role != role:
            return LoginResult(False, reason=f"Este número já tem cadastro de {_ROLE_NAMES.get(user.role, user.role)}.")
        if user is not None and user.is_blocked:
            return LoginResult(False, reason="Conta bloqueada. Fale com o suporte.")
        row.used = True
        is_new = user is None
        if user is None:
            user_id = str(uuid.uuid4())
            repo.add_user(session, user_id=user_id, phone=phone, name="", role=role)
            if role == "passenger":
                repo.add_passenger_profile(session, user_id=user_id)
        else:
            user_id = user.id
        token = secrets.token_urlsafe(32)
        session.add(
            SessionRow(
                token_hash=_token_hash(token), user_id=user_id, device=device[:80],
                created_at=now, expires_at=now + self.cfg.session_days * 86400,
            )
        )
        session.flush()
        return LoginResult(True, token=token, user_id=user_id, role=role, is_new_user=is_new)

    def authenticate(self, session: Session, token: str, now: float) -> AuthUser | None:
        row = session.get(SessionRow, _token_hash(token))
        if row is None or row.revoked or now > row.expires_at:
            return None
        user = session.get(UserRow, row.user_id)
        if user is None or user.is_blocked:
            return None
        return AuthUser(user.id, user.phone, user.name, user.role)

    def logout(self, session: Session, token: str) -> None:
        row = session.get(SessionRow, _token_hash(token))
        if row is not None:
            row.revoked = True
            session.flush()

    def set_name(self, session: Session, user_id: str, name: str) -> None:
        clean = name.strip()
        if not 2 <= len(clean) <= 120:
            raise ValueError("Digite seu nome (de 2 a 120 letras).")
        user = session.get(UserRow, user_id)
        if user is None:
            raise LookupError(f"usuário {user_id} não encontrado")
        user.name = clean
        session.flush()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_events.py tests/services/test_auth.py -v 2>&1 | tail -30`
Expected: todos passam.

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/services/events.py app/services/auth.py app/adapters/fake_otp.py tests/services/test_events.py tests/services/test_auth.py && git commit -m "feat(services): coletor de avisos e login por código com sessões longas" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Cadastro, aprovação e disponibilidade do motoqueiro

**Files:**
- Create: `server/app/db/queries.py`, `server/app/services/riders.py`
- Test: `server/tests/services/test_riders.py`

**Interfaces:**
- Consumes: `PositionStore` (plano 2A), `EventCollector`, `RiderProfileRow`, `UserRow`, `offer_block_reason`, `brl`, `FeeConfig`.
- Produces:
  - Em `app.db.queries`: `RiderCard(rider_id, name, plate, moto_model, rating: float | None, rating_count: int, selfie_key: str | None)` e `rider_card(session, rider_id) -> RiderCard`.
  - Em `app.services.riders`: `validate_cpf(raw) -> str`, `normalize_plate(raw) -> str`, `normalize_cnh(raw) -> str` (levantam `ValueError` com texto para o usuário); `RegistrationError(ValueError)`; `DuplicateRegistration(RegistrationError)` com `.field`; `InvalidState(Exception)`; `CannotGoOnline(Exception)` com `.code` e `.message`.
  - `RiderService(positions, events, fee_cfg=None)` com: `register_rider(session, user_id, *, name, cpf, cnh_number, plate, moto_model, selfie_key, cnh_photo_key, crlv_key, cnh_expires_on, crlv_expires_on, today)`, `approve(session, rider_id, now)`, `reject(session, rider_id, reason)`, `block(session, rider_id, reason)`, `unblock(session, rider_id)`, `renew_documents(session, rider_id, *, cnh_expires_on, crlv_expires_on, today)`, `go_online(session, rider_id, today)`, `go_offline(session, rider_id)`, `report_position(rider_id, point, now)`, `block_expired_documents(session, today) -> list[str]`, `rider_card(session, rider_id) -> RiderCard`.
  - Códigos de `CannotGoOnline.code`: `blocked`, `not_approved`, `documents_expired`, `entry_pending`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `server/tests/helpers_db.py`:

```python
def make_cpf(base: str) -> str:
    """CPF válido a partir de 9 dígitos (calcula os dois dígitos verificadores)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        total = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append((total * 10 % 11) % 10)
    return "".join(map(str, d))
```

`server/tests/services/test_riders.py`:

```python
import datetime as dt

import pytest
from sqlalchemy import select

from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.riders import (
    CannotGoOnline,
    DuplicateRegistration,
    InvalidState,
    RegistrationError,
    RiderService,
    normalize_cnh,
    normalize_plate,
    validate_cpf,
)
from tests.helpers import ORIGIN, pt
from tests.helpers_db import make_cpf

HOJE = dt.date(2026, 10, 9)
FUTURO = dt.date(2030, 1, 1)


CPF1 = make_cpf("123456789")
CPF2 = make_cpf("987654321")


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def service(positions, events):
    return RiderService(positions, events)


def novo_usuario(session, user_id="r1", phone="+5575900000002", role="rider"):
    repo.add_user(session, user_id=user_id, phone=phone, name="", role=role)


def dados(**mudar):
    base = dict(
        name="Carlos Moto", cpf=CPF1, cnh_number="12345678901", plate="abc-1d23", moto_model="Honda CG 160",
        selfie_key="s.jpg", cnh_photo_key="c.jpg", crlv_key="m.jpg",
        cnh_expires_on=FUTURO, crlv_expires_on=FUTURO, today=HOJE,
    )
    base.update(mudar)
    return base


def cadastrar(service, session, user_id="r1", **mudar):
    service.register_rider(session, user_id, **dados(**mudar))


def aprovado(service, session, user_id="r1", phone="+5575900000002", **mudar):
    novo_usuario(session, user_id, phone)
    cadastrar(service, session, user_id, **mudar)
    service.approve(session, user_id, now=100.0)


def test_cpf_valido_vira_formato_com_pontos():
    assert validate_cpf(CPF1) == f"{CPF1[:3]}.{CPF1[3:6]}.{CPF1[6:9]}-{CPF1[9:]}"
    assert validate_cpf(validate_cpf(CPF1)) == validate_cpf(CPF1)


@pytest.mark.parametrize("ruim", ["", "123", "11111111111", CPF1[:-1] + str((int(CPF1[-1]) + 1) % 10), "abc"])
def test_cpf_invalido_e_recusado(ruim):
    with pytest.raises(ValueError, match="CPF"):
        validate_cpf(ruim)


def test_placa_antiga_e_mercosul_viram_maiusculas_sem_hifen():
    assert normalize_plate("abc-1234") == "ABC1234"
    assert normalize_plate(" abc1d23 ") == "ABC1D23"
    for ruim in ("AB1234", "ABCD123", "1234567", ""):
        with pytest.raises(ValueError, match="placa"):
            normalize_plate(ruim)


def test_cnh_tem_11_numeros():
    assert normalize_cnh("123 456 789-01") == "12345678901"
    with pytest.raises(ValueError, match="CNH"):
        normalize_cnh("1234")


def test_cadastro_fica_pendente_com_dados_normalizados(service, session):
    novo_usuario(session)
    cadastrar(service, session)
    perfil = session.get(RiderProfileRow, "r1")
    assert perfil.status == "pending" and perfil.online is False
    assert perfil.plate == "ABC1D23" and perfil.cpf == validate_cpf(CPF1)
    assert session.get(UserRow, "r1").name == "Carlos Moto"


@pytest.mark.parametrize(
    "mudar, trecho",
    [
        (dict(name=" "), "nome"),
        (dict(cpf="123"), "CPF"),
        (dict(plate="XX"), "placa"),
        (dict(cnh_number="1"), "CNH"),
        (dict(moto_model=" "), "modelo"),
        (dict(cnh_expires_on=dt.date(2026, 10, 8)), "CNH está vencida"),
        (dict(crlv_expires_on=dt.date(2026, 10, 8)), "moto está vencido"),
    ],
)
def test_cadastro_com_dado_ruim_e_recusado_com_mensagem_clara(service, session, mudar, trecho):
    novo_usuario(session)
    with pytest.raises(RegistrationError, match=trecho):
        cadastrar(service, session, **mudar)
    assert session.get(RiderProfileRow, "r1") is None


@pytest.mark.parametrize(
    "campo, mudar",
    [
        ("CPF", dict(cnh_number="99999999999", plate="ZZZ9Z99")),
        ("número de CNH", dict(cpf=CPF2, plate="ZZZ9Z99")),
        ("placa", dict(cpf=CPF2, cnh_number="99999999999")),
    ],
)
def test_cpf_cnh_e_placa_nao_se_repetem(service, session, campo, mudar):
    aprovado(service, session)
    novo_usuario(session, "r2", "+5575900000003")
    with pytest.raises(DuplicateRegistration) as erro:
        cadastrar(service, session, "r2", **mudar)
    assert erro.value.field == campo


def test_so_motoqueiro_cadastra_e_so_uma_vez(service, session):
    novo_usuario(session, "p1", "+5575900000009", role="passenger")
    with pytest.raises(RegistrationError, match="motoqueiro"):
        cadastrar(service, session, "p1")
    novo_usuario(session)
    cadastrar(service, session)
    with pytest.raises(RegistrationError, match="já foi enviado"):
        cadastrar(service, session, cpf=CPF2, cnh_number="99999999999", plate="ZZZ9Z99")


def test_aprovar_recusar_bloquear_e_liberar(service, session, events):
    novo_usuario(session)
    cadastrar(service, session)
    service.approve(session, "r1", now=100.0)
    assert session.get(RiderProfileRow, "r1").status == "approved"
    assert session.get(RiderProfileRow, "r1").approved_at is not None
    with pytest.raises(InvalidState):
        service.approve(session, "r1", now=101.0)
    with pytest.raises(InvalidState):
        service.reject(session, "r1", "motivo")
    service.block(session, "r1", "denúncia")
    assert session.get(RiderProfileRow, "r1").status == "blocked"
    assert session.get(UserRow, "r1").is_blocked is True
    service.unblock(session, "r1")
    assert session.get(RiderProfileRow, "r1").status == "approved"
    assert session.get(UserRow, "r1").is_blocked is False
    assert [e.type for e in events.events] == ["rider_approved", "rider_blocked", "rider_unblocked"]


def test_cadastro_recusado_guarda_o_motivo(service, session):
    novo_usuario(session)
    cadastrar(service, session)
    service.reject(session, "r1", "Foto da CNH ilegível")
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.status, perfil.rejected_reason) == ("rejected", "Foto da CNH ilegível")


def test_ficar_disponivel_exige_cadastro_aprovado(service, session):
    novo_usuario(session)
    cadastrar(service, session)
    with pytest.raises(CannotGoOnline) as erro:
        service.go_online(session, "r1", HOJE)
    assert erro.value.code == "not_approved"
    service.approve(session, "r1", now=100.0)
    service.go_online(session, "r1", HOJE)
    assert session.get(RiderProfileRow, "r1").online is True


def test_ficar_disponivel_recusa_bloqueado_e_documento_vencido(service, session):
    aprovado(service, session)
    service.block(session, "r1", "teste")
    with pytest.raises(CannotGoOnline) as erro:
        service.go_online(session, "r1", HOJE)
    assert erro.value.code == "blocked"
    service.unblock(session, "r1")
    with pytest.raises(CannotGoOnline) as erro:
        service.go_online(session, "r1", FUTURO + dt.timedelta(days=1))
    assert erro.value.code == "documents_expired"


def test_depois_das_10_corridas_so_fica_disponivel_com_a_entrada_paga(service, session):
    aprovado(service, session)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 10
    repo.save_rider_account(session, acc)
    with pytest.raises(CannotGoOnline) as erro:
        service.go_online(session, "r1", HOJE)
    assert erro.value.code == "entry_pending" and "R$ 50,00" in erro.value.message
    acc.entry_paid = True
    repo.save_rider_account(session, acc)
    service.go_online(session, "r1", HOJE)


def test_ficar_indisponivel_tira_a_moto_do_mapa(service, session, positions):
    aprovado(service, session)
    service.go_online(session, "r1", HOJE)
    service.report_position("r1", ORIGIN, now=100.0)
    assert positions.get("r1") is not None
    service.go_offline(session, "r1")
    assert session.get(RiderProfileRow, "r1").online is False
    assert positions.get("r1") is None


def test_documentos_vencidos_bloqueiam_e_tiram_da_disponibilidade(service, session, positions, events):
    aprovado(service, session, "r1")
    aprovado(service, session, "r2", phone="+5575900000003", cpf=CPF2, cnh_number="99999999999",
             plate="ZZZ9Z99", crlv_expires_on=dt.date(2026, 12, 31))
    for rider in ("r1", "r2"):
        service.go_online(session, rider, HOJE)
        service.report_position(rider, ORIGIN, now=100.0)
    events.drain()
    bloqueados = service.block_expired_documents(session, dt.date(2027, 1, 1))
    assert bloqueados == ["r2"]
    assert session.get(RiderProfileRow, "r2").status == "blocked"
    assert session.get(RiderProfileRow, "r2").online is False
    assert positions.get("r2") is None and positions.get("r1") is not None
    assert [e.type for e in events.events] == ["documents_expired"]
    assert service.block_expired_documents(session, dt.date(2027, 1, 1)) == []


def test_renovar_documentos_atualiza_as_datas(service, session):
    aprovado(service, session)
    service.renew_documents(session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE)
    assert session.get(RiderProfileRow, "r1").cnh_expires_on == dt.date(2032, 1, 1)
    with pytest.raises(RegistrationError, match="vencid"):
        service.renew_documents(session, "r1", cnh_expires_on=dt.date(2020, 1, 1), crlv_expires_on=FUTURO, today=HOJE)


def test_ficha_do_motoqueiro_para_o_passageiro(service, session):
    aprovado(service, session)
    ficha = service.rider_card(session, "r1")
    assert (ficha.name, ficha.plate, ficha.moto_model) == ("Carlos Moto", "ABC1D23", "Honda CG 160")
    assert ficha.rating is None and ficha.rating_count == 0
    perfil = session.get(RiderProfileRow, "r1")
    perfil.rating_sum, perfil.rating_count = 14, 3
    session.flush()
    ficha = service.rider_card(session, "r1")
    assert ficha.rating == 4.7 and ficha.rating_count == 3
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_riders.py -q 2>&1 | tail -5`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.services.riders'`.

- [ ] **Step 3: Implementar**

`server/app/db/queries.py`:

```python
"""Consultas de leitura usadas pelos serviços. Sem regra de negócio, só perguntas ao banco."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RiderProfileRow, UserRow


@dataclass(frozen=True)
class RiderCard:
    """A ficha que o passageiro vê (spec, seção 8): sem selo de permissão da prefeitura."""

    rider_id: str
    name: str
    plate: str
    moto_model: str
    rating: float | None
    rating_count: int
    selfie_key: str | None


def rider_card(session: Session, rider_id: str) -> RiderCard:
    found = session.execute(
        select(RiderProfileRow, UserRow.name)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(RiderProfileRow.user_id == rider_id)
    ).one_or_none()
    if found is None:
        raise LookupError(f"motoqueiro {rider_id} não encontrado")
    profile, name = found
    rating = round(profile.rating_sum / profile.rating_count, 1) if profile.rating_count else None
    return RiderCard(
        rider_id=rider_id, name=name, plate=profile.plate, moto_model=profile.moto_model,
        rating=rating, rating_count=profile.rating_count, selfie_key=profile.selfie_key,
    )
```

`server/app/services/riders.py`:

```python
"""Cadastro, aprovação e disponibilidade do motoqueiro (spec, seções 4 e 8)."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from app.domain.config import FeeConfig
from app.domain.fees import offer_block_reason
from app.domain.geo import GeoPoint
from app.domain.money import brl
from app.infra.redis_store import PositionStore
from app.services.events import EventCollector


class RegistrationError(ValueError):
    """Dado do cadastro inválido. A mensagem é para o motoqueiro."""


class DuplicateRegistration(RegistrationError):
    def __init__(self, field: str, phrase: str) -> None:
        super().__init__(f"Já existe um cadastro com {phrase}.")
        self.field = field


class InvalidState(Exception):
    """A ação não vale para o estado atual do cadastro."""


class CannotGoOnline(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_cpf(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 11 or len(set(digits)) == 1:
        raise ValueError("CPF inválido.")
    for n in (9, 10):
        total = sum(int(digits[i]) * (n + 1 - i) for i in range(n))
        if (total * 10 % 11) % 10 != int(digits[n]):
            raise ValueError("CPF inválido.")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def normalize_plate(raw: str) -> str:
    plate = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", plate):
        raise ValueError("Confira a placa da moto.")
    return plate


def normalize_cnh(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 11:
        raise ValueError("Confira o número da CNH (11 números).")
    return digits


class RiderService:
    def __init__(self, positions: PositionStore, events: EventCollector, fee_cfg: FeeConfig | None = None) -> None:
        self.positions = positions
        self.events = events
        self.fee_cfg = fee_cfg or FeeConfig()

    # --- cadastro -----------------------------------------------------------------

    def register_rider(
        self,
        session: Session,
        user_id: str,
        *,
        name: str,
        cpf: str,
        cnh_number: str,
        plate: str,
        moto_model: str,
        selfie_key: str,
        cnh_photo_key: str,
        crlv_key: str,
        cnh_expires_on: dt.date,
        crlv_expires_on: dt.date,
        today: dt.date,
    ) -> None:
        user = session.get(UserRow, user_id)
        if user is None or user.role != "rider":
            raise RegistrationError("Entre com um número de motoqueiro para se cadastrar.")
        if session.get(RiderProfileRow, user_id) is not None:
            raise RegistrationError("Seu cadastro já foi enviado.")
        clean_name = name.strip()
        if len(clean_name) < 2:
            raise RegistrationError("Digite seu nome completo.")
        try:
            cpf_ok, cnh_ok, plate_ok = validate_cpf(cpf), normalize_cnh(cnh_number), normalize_plate(plate)
        except ValueError as exc:
            raise RegistrationError(str(exc)) from exc
        if not moto_model.strip():
            raise RegistrationError("Informe o modelo da moto.")
        if cnh_expires_on < today:
            raise RegistrationError("Sua CNH está vencida.")
        if crlv_expires_on < today:
            raise RegistrationError("O documento da moto está vencido.")
        for field, phrase, column, value in (
            ("CPF", "este CPF", RiderProfileRow.cpf, cpf_ok),
            ("número de CNH", "este número de CNH", RiderProfileRow.cnh_number, cnh_ok),
            ("placa", "esta placa", RiderProfileRow.plate, plate_ok),
        ):
            if session.execute(select(RiderProfileRow.user_id).where(column == value)).first() is not None:
                raise DuplicateRegistration(field, phrase)
        user.name = clean_name
        session.add(
            RiderProfileRow(
                user_id=user_id, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok, moto_model=moto_model.strip(),
                status="pending", selfie_key=selfie_key, cnh_photo_key=cnh_photo_key, crlv_key=crlv_key,
                cnh_expires_on=cnh_expires_on, crlv_expires_on=crlv_expires_on,
            )
        )
        session.flush()

    def _profile(self, session: Session, rider_id: str) -> RiderProfileRow:
        row = session.execute(
            select(RiderProfileRow).where(RiderProfileRow.user_id == rider_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"motoqueiro {rider_id} não encontrado")
        return row

    def approve(self, session: Session, rider_id: str, now: float) -> None:
        profile = self._profile(session, rider_id)
        if profile.status != "pending":
            raise InvalidState(f"o cadastro está {profile.status}, não dá para aprovar")
        profile.status = "approved"
        profile.approved_at = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        session.flush()
        self.events.add(rider_id, "rider_approved")

    def reject(self, session: Session, rider_id: str, reason: str) -> None:
        profile = self._profile(session, rider_id)
        if profile.status != "pending":
            raise InvalidState(f"o cadastro está {profile.status}, não dá para recusar")
        profile.status = "rejected"
        profile.rejected_reason = reason[:200]
        session.flush()
        self.events.add(rider_id, "rider_rejected", {"reason": reason})

    def block(self, session: Session, rider_id: str, reason: str) -> None:
        profile = self._profile(session, rider_id)
        profile.status = "blocked"
        profile.online = False
        profile.rejected_reason = reason[:200]
        session.get(UserRow, rider_id).is_blocked = True
        self.positions.remove(rider_id)
        session.flush()
        self.events.add(rider_id, "rider_blocked", {"reason": reason})

    def unblock(self, session: Session, rider_id: str) -> None:
        profile = self._profile(session, rider_id)
        if profile.status != "blocked":
            raise InvalidState("o cadastro não está bloqueado")
        profile.status = "approved"
        profile.rejected_reason = None
        session.get(UserRow, rider_id).is_blocked = False
        session.flush()
        self.events.add(rider_id, "rider_unblocked")

    def renew_documents(
        self, session: Session, rider_id: str, *, cnh_expires_on: dt.date, crlv_expires_on: dt.date, today: dt.date
    ) -> None:
        if cnh_expires_on < today or crlv_expires_on < today:
            raise RegistrationError("As novas datas já estão vencidas.")
        profile = self._profile(session, rider_id)
        profile.cnh_expires_on = cnh_expires_on
        profile.crlv_expires_on = crlv_expires_on
        session.flush()

    # --- disponibilidade ----------------------------------------------------------

    def go_online(self, session: Session, rider_id: str, today: dt.date) -> None:
        profile = self._profile(session, rider_id)
        if profile.status == "blocked" or session.get(UserRow, rider_id).is_blocked:
            raise CannotGoOnline("blocked", "Sua conta está bloqueada. Fale com o suporte.")
        if profile.status != "approved":
            raise CannotGoOnline("not_approved", "Seu cadastro ainda não foi aprovado.")
        if (profile.cnh_expires_on and profile.cnh_expires_on < today) or (
            profile.crlv_expires_on and profile.crlv_expires_on < today
        ):
            raise CannotGoOnline("documents_expired", "Um dos seus documentos venceu. Envie o novo para continuar.")
        if offer_block_reason(repo.get_rider_account(session, rider_id), self.fee_cfg) is not None:
            raise CannotGoOnline(
                "entry_pending",
                f"Você fez as {self.fee_cfg.trial_rides} corridas de teste. "
                f"Pague a entrada de {brl(self.fee_cfg.entry_fee_cents)} para continuar.",
            )
        profile.online = True
        session.flush()

    def go_offline(self, session: Session, rider_id: str) -> None:
        profile = self._profile(session, rider_id)
        profile.online = False
        session.flush()
        self.positions.remove(rider_id)

    def report_position(self, rider_id: str, point: GeoPoint, now: float) -> None:
        """Guarda a posição atual (a cada ~4 s). Quem chama já conferiu quem é o motoqueiro."""
        self.positions.update(rider_id, point, now)

    def block_expired_documents(self, session: Session, today: dt.date) -> list[str]:
        rows = session.execute(
            select(RiderProfileRow)
            .where(
                RiderProfileRow.status == "approved",
                (RiderProfileRow.cnh_expires_on < today) | (RiderProfileRow.crlv_expires_on < today),
            )
            .order_by(RiderProfileRow.user_id)
            .with_for_update()
        ).scalars().all()
        blocked: list[str] = []
        for profile in rows:
            profile.status = "blocked"
            profile.online = False
            profile.rejected_reason = "documento vencido"
            self.positions.remove(profile.user_id)
            self.events.add(profile.user_id, "documents_expired")
            blocked.append(profile.user_id)
        session.flush()
        return blocked

    def rider_card(self, session: Session, rider_id: str) -> queries.RiderCard:
        return queries.rider_card(session, rider_id)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_riders.py -v 2>&1 | tail -45`
Expected: todos passam.

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app/db/queries.py app/services/riders.py tests/services/test_riders.py && git commit -m "feat(services): cadastro, aprovação, bloqueio por documento vencido e disponibilidade do motoqueiro" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Preço e pedido de corrida

**Files:**
- Create: `server/app/domain/maps.py`, `server/app/domain/ids.py`, `server/app/services/quotes.py`, `server/app/services/ride_requests.py`
- Modify: `server/app/adapters/fake_maps.py`, `server/app/infra/redis_store.py`, `server/app/db/repositories.py`, `server/app/db/queries.py`, `server/tests/helpers_db.py`
- Test: `server/tests/services/test_quotes.py`, `server/tests/services/test_ride_requests.py`, `server/tests/infra/test_factor_store.py`

**Interfaces:**
- Consumes: `target_factor`, `smooth_factor`, `final_price_cents`, `price_reason` (`app.domain.pricing`); `PositionStore`; `AppConfig`; `Ride`, `start_search`.
- Produces:
  - `Route(distance_m: int, duration_s: int, points: tuple[GeoPoint, ...])` e `MapsProvider` (Protocol com `route(origin, destination) -> Route` e `eta_seconds(origin, destination) -> int`) em `app.domain.maps`; `FakeMaps` em `app.adapters.fake_maps` (distância = linha reta × 1,3).
  - `new_id(prefix) -> str` em `app.domain.ids`.
  - `FactorStore` (Protocol: `get() -> float | None`, `set(value)`), `InMemoryFactorStore`, `RedisFactorStore(client, key="price:factor")`.
  - Em `repositories`: `RideDetails(pickup, destination, pickup_text, destination_text, distance_m, price_factor, price_reason)`, `set_ride_details(session, ride_id, details)`, `get_ride_details(session, ride_id)`, `log_ride_event(session, ride_id, kind, data, now)`, `ride_events(session, ride_id) -> list[tuple[str, dict]]`.
  - Em `queries`: `passenger_open_ride_id(session, passenger_id) -> str | None`, `passenger_unpaid_cash_ride_id(session, passenger_id) -> str | None`, `count_searching_rides(session) -> int`, `free_online_rider_ids(session, rider_ids) -> list[str]`.
  - Em `app.services.quotes`: `Quote`, `NotAllowed`, `QuoteExpired`, `passenger_block_reason(session, passenger_id) -> str | None`, `QuoteService(maps, positions, factors, cfg=None).create_quote(session, passenger_id, pickup, destination, pickup_text, destination_text, now) -> Quote`.
  - Em `app.services.ride_requests`: `OfferDispatcher` (Protocol: `offer_next(session, ride_id, now) -> str | None`) e `RideRequestService(dispatcher, events, cfg=None).request_ride(session, passenger_id, quote_id, method, now) -> Ride`.
  - Em `tests/helpers_db.py`: `make_online_rider(session, positions, n, point, now=100.0) -> str` e `add_searching_ride(session, ride_id="ride-1", passenger_id="p1", method=PaymentMethod.PIX, price=700, pickup=ORIGIN, destination=None, now=10.0) -> Ride`.
  - Em `config_store.AppConfig`: `AppConfig.defaults()`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `server/tests/helpers_db.py` (e ao bloco de importações do topo: `from app.db.models import RiderProfileRow`, `from app.domain.geo import GeoPoint`, `from tests.helpers import ORIGIN, pt`):

```python
def make_online_rider(session, positions, n: int, point: GeoPoint, now: float = 100.0) -> str:
    """Motoqueiro aprovado, disponível e com posição fresca. `n` torna CPF, CNH, placa e telefone únicos."""
    rider_id = f"r{n}"
    add_rider(
        session, user_id=rider_id, phone=f"+55759{n:08d}", cpf=f"{n:011d}", cnh=f"{n:011d}", plate=f"ABC{n:04d}"
    )
    profile = session.get(RiderProfileRow, rider_id)
    profile.status, profile.online = "approved", True
    session.flush()
    positions.update(rider_id, point, now)
    return rider_id


def add_searching_ride(
    session,
    ride_id: str = "ride-1",
    passenger_id: str = "p1",
    method: PaymentMethod = PaymentMethod.PIX,
    price: int = 700,
    pickup: GeoPoint = ORIGIN,
    destination: GeoPoint | None = None,
    now: float = 10.0,
) -> Ride:
    ride = Ride(ride_id, passenger_id, price, method, pin="4821")
    start_search(ride, now)
    repo.add_ride(session, ride)
    repo.set_ride_details(
        session, ride_id,
        repo.RideDetails(pickup, destination or pt(1500, 0), "Rua A", "Feira livre", 1950, 1.0, "Preço normal."),
    )
    return ride
```

`server/tests/infra/test_factor_store.py`:

```python
from app.infra.redis_store import InMemoryFactorStore, RedisFactorStore


def test_fator_em_memoria():
    store = InMemoryFactorStore()
    assert store.get() is None
    store.set(1.1)
    assert store.get() == 1.1


def test_fator_no_redis_sobrevive_ao_cliente(redis_client):
    store = RedisFactorStore(redis_client)
    assert store.get() is None
    store.set(0.9)
    assert RedisFactorStore(redis_client).get() == 0.9
```

`server/tests/services/test_quotes.py`:

```python
import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow, RiderProfileRow, UserRow
from app.domain.rides import PassengerAccount
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.quotes import NotAllowed, QuoteService, passenger_block_reason
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider, add_searching_ride, make_online_rider

DESTINO = pt(1500, 0)  # em linha reta 1.500 m; no mapa falso vira 1.950 m (x 1,3)


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def factors():
    return InMemoryFactorStore()


@pytest.fixture()
def service(positions, factors):
    return QuoteService(FakeMaps(), positions, factors)


def cotar(service, session, now=1000.0, passenger="p1"):
    return service.create_quote(session, passenger, ORIGIN, DESTINO, "Rua A", "Feira livre", now)


def test_cotacao_normal_sem_demanda_e_sem_motos(service, session, factors):
    add_passenger(session)
    quote = cotar(service, session)
    assert quote.quote_id.startswith("q-")
    assert abs(quote.distance_m - 1950) <= 5
    assert quote.price_cents == 600 and quote.factor == 1.0
    assert quote.reason == "Preço normal para este horário."
    assert quote.expires_at == 1300.0
    row = session.execute(select(QuoteRow)).scalar_one()
    assert (row.id, row.passenger_id, row.price_cents, row.used) == (quote.quote_id, "p1", 600, False)
    assert factors.get() == 1.0


def test_muito_pedido_e_pouca_moto_sobe_o_preco_aos_poucos(service, session, factors):
    add_passenger(session)
    for i in (2, 3, 4):
        add_passenger(session, f"p{i}", f"+5575900001{i:03d}")
        add_searching_ride(session, f"ride-{i}", f"p{i}")
    primeira = cotar(service, session, now=1000.0)
    assert primeira.factor == pytest.approx(1.1) and primeira.price_cents == 650
    segunda = cotar(service, session, now=1010.0)
    assert segunda.factor == pytest.approx(1.2) and segunda.price_cents == 700
    assert segunda.reason == "Poucas motos agora, preço maior."


def test_muita_moto_livre_baixa_o_preco(service, session, positions):
    add_passenger(session)
    for n in range(1, 5):
        make_online_rider(session, positions, n, pt(300 * n, 0), now=100.0)
    quote = cotar(service, session, now=110.0)
    assert quote.factor == pytest.approx(0.9) and quote.price_cents == 550
    assert quote.reason == "Muita moto livre agora, preço menor."


def test_moto_offline_velha_ou_ocupada_nao_conta_como_livre(service, session, positions):
    add_passenger(session)
    add_passenger(session, "p9", "+5575900001999")
    off = make_online_rider(session, positions, 1, pt(300, 0), now=100.0)
    session.get(RiderProfileRow, off).online = False
    make_online_rider(session, positions, 2, pt(400, 0), now=10.0)         # posição de 100 s atrás
    ocupada = make_online_rider(session, positions, 3, pt(500, 0), now=100.0)
    add_accepted_ride(session, ride_id="ride-9", passenger_id="p9", rider_id=ocupada)
    session.flush()
    quote = cotar(service, session, now=110.0)
    assert quote.factor == 1.0 and quote.price_cents == 600


def test_passageiro_com_restricao_nao_recebe_preco(service, session):
    add_passenger(session)
    session.get(UserRow, "p1").is_blocked = True
    session.flush()
    with pytest.raises(NotAllowed, match="bloqueada"):
        cotar(service, session)
    assert session.execute(select(QuoteRow)).first() is None


def test_motivos_para_nao_poder_pedir(session):
    add_passenger(session)
    add_rider(session)
    assert passenger_block_reason(session, "p1") is None
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=0))
    add_searching_ride(session, "ride-1", "p1")
    assert "já tem uma corrida" in passenger_block_reason(session, "p1")


def test_corrida_em_dinheiro_concluida_e_nao_paga_impede_novo_pedido(session):
    from app.domain.rides import RideState
    from app.domain.types import PaymentMethod

    add_passenger(session)
    add_rider(session)
    ride = add_accepted_ride(session, method=PaymentMethod.CASH)
    ride.state = RideState.COMPLETED
    repo.save_ride(session, ride)
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    ride.end_payment_confirmed = True
    repo.save_ride(session, ride)
    assert passenger_block_reason(session, "p1") is None
```

`server/tests/services/test_ride_requests.py`:

```python
import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow
from app.domain.rides import PassengerAccount, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteExpired, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger


class DespachanteFalso:
    def __init__(self):
        self.chamadas = []

    def offer_next(self, session, ride_id, now):
        self.chamadas.append((ride_id, now))
        return None


@pytest.fixture()
def quotes():
    return QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())


@pytest.fixture()
def despachante():
    return DespachanteFalso()


@pytest.fixture()
def requests(despachante):
    return RideRequestService(despachante, EventCollector())


def cotar(quotes, session, now=1000.0, passenger="p1"):
    return quotes.create_quote(session, passenger, ORIGIN, pt(1500, 0), "Rua A", "Feira livre", now)


def test_pedido_cria_corrida_em_procura_com_o_preco_travado(quotes, requests, despachante, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    ride = requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    assert ride.state is RideState.SEARCHING and ride.searching_since == 1010.0
    assert ride.price_cents == quote.price_cents == 600
    assert len(ride.pin) == 4 and ride.pin.isdigit()
    detalhes = repo.get_ride_details(session, ride.ride_id)
    assert (detalhes.pickup_text, detalhes.destination_text) == ("Rua A", "Feira livre")
    assert abs(detalhes.pickup.lat - ORIGIN.lat) < 1e-9 and detalhes.price_factor == 1.0
    assert session.execute(select(QuoteRow.used)).scalar_one() is True
    assert [kind for kind, _ in repo.ride_events(session, ride.ride_id)] == ["requested"]
    assert despachante.chamadas == [(ride.ride_id, 1010.0)]
    assert repo.get_ride(session, ride.ride_id) == ride


def test_o_mesmo_preco_nao_serve_duas_vezes(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1010.0)
    with pytest.raises(QuoteExpired, match="Peça de novo"):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1011.0)


def test_preco_vencido_ou_inexistente_ou_de_outra_pessoa_nao_vale(quotes, requests, session):
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000012")
    quote = cotar(quotes, session)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1000.0 + 301)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p2", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    with pytest.raises(QuoteExpired):
        requests.request_ride(session, "p1", "q-nao-existe", PaymentMethod.PIX, now=1010.0)
    assert session.execute(select(QuoteRow.used)).scalar_one() is False


def test_passageiro_com_pagamento_pendente_nao_pede(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    repo.save_passenger_account(session, PassengerAccount("p1", unpaid_cents=700))
    with pytest.raises(NotAllowed, match="Falta pagar"):
        requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.PIX, now=1010.0)
    assert session.execute(select(QuoteRow.used)).scalar_one() is False


def test_nao_da_para_ter_duas_corridas_abertas(quotes, requests, session):
    add_passenger(session)
    primeira = cotar(quotes, session)
    requests.request_ride(session, "p1", primeira.quote_id, PaymentMethod.PIX, now=1010.0)
    with pytest.raises(NotAllowed, match="já tem uma corrida"):
        cotar(quotes, session, now=1020.0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/infra/test_factor_store.py tests/services/test_quotes.py tests/services/test_ride_requests.py -q 2>&1 | tail -6`
Expected: erro de coleta (`ImportError ... FactorStore` / `ModuleNotFoundError ... app.services.quotes`).

- [ ] **Step 3: Implementar**

`server/app/domain/maps.py`:

```python
"""Tipos de mapa que o resto do sistema usa. O Google Maps (plano 7) e o mapa falso cumprem este contrato."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.geo import GeoPoint


@dataclass(frozen=True)
class Route:
    distance_m: int
    duration_s: int
    points: tuple[GeoPoint, ...]


class MapsProvider(Protocol):
    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route: ...

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int: ...
```

`server/app/domain/ids.py`:

```python
from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Identificador curto e único, por exemplo `ride-3f9a1c0b7d2e4a5f` (cabe nas colunas de 40 letras)."""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
```

Em `server/app/adapters/fake_maps.py`, acrescentar no fim (e `from app.domain.maps import Route` no topo):

```python


class FakeMaps(StraightLineEta):
    """Mapa falso: a rua é 30% mais longa que a linha reta e a rota é um segmento só."""

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        distance = haversine_m(origin, destination) * 1.3
        return Route(
            distance_m=int(round(distance)),
            duration_s=int(distance / self.speed_mps),
            points=(origin, destination),
        )
```

Em `server/app/infra/redis_store.py`, acrescentar no fim:

```python


class FactorStore(Protocol):
    def get(self) -> float | None: ...

    def set(self, value: float) -> None: ...


class InMemoryFactorStore:
    def __init__(self) -> None:
        self._value: float | None = None

    def get(self) -> float | None:
        return self._value

    def set(self, value: float) -> None:
        self._value = value


class RedisFactorStore:
    """Fator de preço atual (muda aos poucos, então precisa lembrar o valor anterior)."""

    def __init__(self, client: redis.Redis, key: str = "price:factor") -> None:
        self.r = client
        self.key = key

    def get(self) -> float | None:
        value = self.r.get(self.key)
        return float(value) if value is not None else None

    def set(self, value: float) -> None:
        self.r.set(self.key, repr(value))
```

Em `server/app/db/config_store.py`, na classe `AppConfig`, depois do campo `auth`, acrescentar:

```python

    @classmethod
    def defaults(cls) -> "AppConfig":
        return cls(PricingConfig(), FeeConfig(), RideConfig(), DispatchConfig(), SafetyConfig())
```

Em `server/app/db/repositories.py`: acrescentar `import datetime`-free imports `from dataclasses import dataclass` e `from app.domain.geo import GeoPoint` e `RideEventRow` à lista de modelos importados; e no fim do arquivo:

```python


# --- detalhes da corrida e eventos ---------------------------------------------------


@dataclass(frozen=True)
class RideDetails:
    pickup: GeoPoint
    destination: GeoPoint
    pickup_text: str
    destination_text: str
    distance_m: int
    price_factor: float
    price_reason: str


def set_ride_details(session: Session, ride_id: str, details: RideDetails) -> None:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    row.pickup_lat, row.pickup_lng = details.pickup.lat, details.pickup.lng
    row.dest_lat, row.dest_lng = details.destination.lat, details.destination.lng
    row.pickup_text, row.dest_text = details.pickup_text, details.destination_text
    row.distance_m, row.price_factor, row.price_reason = details.distance_m, details.price_factor, details.price_reason
    session.flush()


def get_ride_details(session: Session, ride_id: str) -> RideDetails:
    row = session.get(RideRow, ride_id)
    if row is None:
        raise LookupError(f"corrida {ride_id} não encontrada")
    if row.pickup_lat is None or row.dest_lat is None:
        raise LookupError(f"corrida {ride_id} sem detalhes de trajeto")
    return RideDetails(
        pickup=GeoPoint(row.pickup_lat, row.pickup_lng),
        destination=GeoPoint(row.dest_lat, row.dest_lng),
        pickup_text=row.pickup_text or "",
        destination_text=row.dest_text or "",
        distance_m=row.distance_m or 0,
        price_factor=row.price_factor if row.price_factor is not None else 1.0,
        price_reason=row.price_reason or "",
    )


def log_ride_event(session: Session, ride_id: str, kind: str, data: dict | None, now: float) -> None:
    session.add(RideEventRow(ride_id=ride_id, kind=kind, data=data or {}, created_at=now))
    session.flush()


def ride_events(session: Session, ride_id: str) -> list[tuple[str, dict]]:
    rows = session.execute(
        select(RideEventRow).where(RideEventRow.ride_id == ride_id).order_by(RideEventRow.id)
    ).scalars()
    return [(r.kind, r.data) for r in rows]
```

Em `server/app/db/queries.py`: acrescentar às importações `from sqlalchemy import func, select`, `from app.db.models import RideRow` e `from app.domain.rides import RideState`; e no fim:

```python


_TERMINAL = (RideState.COMPLETED.value, RideState.CANCELLED.value, RideState.NO_RIDER.value)
_ACTIVE = (RideState.ACCEPTED.value, RideState.ARRIVED.value, RideState.IN_PROGRESS.value)


def passenger_open_ride_id(session: Session, passenger_id: str) -> str | None:
    """Corrida do passageiro que ainda não terminou (procurando, na fila, a caminho ou andando)."""
    return session.execute(
        select(RideRow.id).where(RideRow.passenger_id == passenger_id, RideRow.state.notin_(_TERMINAL)).limit(1)
    ).scalar_one_or_none()


def passenger_unpaid_cash_ride_id(session: Session, passenger_id: str) -> str | None:
    """Corrida em dinheiro já concluída, mas ainda sem pagamento confirmado."""
    return session.execute(
        select(RideRow.id)
        .where(
            RideRow.passenger_id == passenger_id,
            RideRow.state == RideState.COMPLETED.value,
            RideRow.payment_method == "cash",
            RideRow.end_payment_confirmed.is_(False),
        )
        .limit(1)
    ).scalar_one_or_none()


def count_searching_rides(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(RideRow).where(RideRow.state == RideState.SEARCHING.value)
    ).scalar_one()


def free_online_rider_ids(session: Session, rider_ids: list[str]) -> list[str]:
    """Dos motoqueiros dados, os que estão aprovados, disponíveis, sem bloqueio e sem corrida."""
    if not rider_ids:
        return []
    busy = select(RideRow.rider_id).where(
        RideRow.rider_id.in_(rider_ids), RideRow.state.in_((*_ACTIVE, RideState.QUEUED.value))
    )
    stmt = (
        select(RiderProfileRow.user_id)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(
            RiderProfileRow.user_id.in_(rider_ids),
            RiderProfileRow.online.is_(True),
            RiderProfileRow.status == "approved",
            UserRow.is_blocked.is_(False),
            RiderProfileRow.user_id.notin_(busy),
        )
        .order_by(RiderProfileRow.user_id)
    )
    return list(session.execute(stmt).scalars())
```

`server/app/services/quotes.py`:

```python
"""Preço mostrado antes do pedido (spec, seção 6) e quem pode pedir."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow, UserRow
from app.domain.geo import GeoPoint
from app.domain.ids import new_id
from app.domain.maps import MapsProvider
from app.domain.pricing import final_price_cents, price_reason, smooth_factor, target_factor
from app.infra.redis_store import FactorStore, PositionStore


class NotAllowed(Exception):
    """O passageiro não pode pedir agora. A mensagem é para ele."""


class QuoteExpired(Exception):
    """O preço não existe, venceu, já foi usado ou é de outra pessoa."""


@dataclass(frozen=True)
class Quote:
    quote_id: str
    price_cents: int
    distance_m: int
    duration_s: int
    factor: float
    reason: str
    expires_at: float
    pickup: GeoPoint
    destination: GeoPoint
    pickup_text: str
    destination_text: str


def passenger_block_reason(session: Session, passenger_id: str) -> str | None:
    user = session.get(UserRow, passenger_id)
    if user is None:
        raise LookupError(f"passageiro {passenger_id} não encontrado")
    if user.is_blocked:
        return "Sua conta está bloqueada. Fale com o suporte."
    if repo.get_passenger_account(session, passenger_id).unpaid_cents > 0 or queries.passenger_unpaid_cash_ride_id(
        session, passenger_id
    ):
        return "Falta pagar a última corrida. Pague para pedir outra moto."
    if queries.passenger_open_ride_id(session, passenger_id):
        return "Você já tem uma corrida em andamento."
    return None


class QuoteService:
    def __init__(
        self, maps: MapsProvider, positions: PositionStore, factors: FactorStore, cfg: AppConfig | None = None
    ) -> None:
        self.maps = maps
        self.positions = positions
        self.factors = factors
        self.cfg = cfg or AppConfig.defaults()

    def create_quote(
        self,
        session: Session,
        passenger_id: str,
        pickup: GeoPoint,
        destination: GeoPoint,
        pickup_text: str,
        destination_text: str,
        now: float,
    ) -> Quote:
        reason_blocked = passenger_block_reason(session, passenger_id)
        if reason_blocked:
            raise NotAllowed(reason_blocked)
        route = self.maps.route(pickup, destination)
        near = self.positions.nearby(
            pickup, self.cfg.dispatch.search_radius_m, now, self.cfg.dispatch.position_max_age_s
        )
        free = len(queries.free_online_rider_ids(session, [rider_id for rider_id, _ in near]))
        pending = queries.count_searching_rides(session)
        previous = self.factors.get()
        factor = smooth_factor(
            previous if previous is not None else 1.0, target_factor(pending, free, self.cfg.pricing), self.cfg.pricing
        )
        self.factors.set(factor)
        price = final_price_cents(route.distance_m, factor, self.cfg.pricing)
        quote = Quote(
            quote_id=new_id("q"), price_cents=price, distance_m=route.distance_m, duration_s=route.duration_s,
            factor=factor, reason=price_reason(factor), expires_at=now + self.cfg.rides.quote_ttl_s,
            pickup=pickup, destination=destination, pickup_text=pickup_text, destination_text=destination_text,
        )
        session.add(
            QuoteRow(
                id=quote.quote_id, passenger_id=passenger_id,
                pickup_lat=pickup.lat, pickup_lng=pickup.lng, dest_lat=destination.lat, dest_lng=destination.lng,
                pickup_text=pickup_text[:200], dest_text=destination_text[:200],
                distance_m=route.distance_m, duration_s=route.duration_s, price_cents=price,
                factor=factor, reason=quote.reason, created_at=now, expires_at=quote.expires_at,
            )
        )
        session.flush()
        return quote
```

`server/app/services/ride_requests.py`:

```python
"""Pedido de corrida: transforma o preço mostrado em uma corrida em procura (spec, seção 5.1)."""
from __future__ import annotations

import secrets
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import QuoteRow
from app.domain.geo import GeoPoint
from app.domain.ids import new_id
from app.domain.rides import Ride, start_search
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteExpired, passenger_block_reason


class OfferDispatcher(Protocol):
    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None: ...


class RideRequestService:
    def __init__(
        self, dispatcher: OfferDispatcher | None, events: EventCollector, cfg: AppConfig | None = None
    ) -> None:
        self.dispatcher = dispatcher
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def request_ride(
        self, session: Session, passenger_id: str, quote_id: str, method: PaymentMethod, now: float
    ) -> Ride:
        quote = session.execute(select(QuoteRow).where(QuoteRow.id == quote_id).with_for_update()).scalar_one_or_none()
        if quote is None or quote.passenger_id != passenger_id or quote.used or now > quote.expires_at:
            raise QuoteExpired("Esse preço não vale mais. Peça de novo.")
        blocked = passenger_block_reason(session, passenger_id)
        if blocked:
            raise NotAllowed(blocked)
        ride = Ride(
            ride_id=new_id("ride"), passenger_id=passenger_id, price_cents=quote.price_cents,
            payment_method=method, pin=f"{secrets.randbelow(10000):04d}",
        )
        start_search(ride, now)
        repo.add_ride(session, ride)
        repo.set_ride_details(
            session, ride.ride_id,
            repo.RideDetails(
                pickup=GeoPoint(quote.pickup_lat, quote.pickup_lng),
                destination=GeoPoint(quote.dest_lat, quote.dest_lng),
                pickup_text=quote.pickup_text, destination_text=quote.dest_text,
                distance_m=quote.distance_m, price_factor=quote.factor, price_reason=quote.reason,
            ),
        )
        quote.used = True
        repo.log_ride_event(
            session, ride.ride_id, "requested",
            {"price_cents": ride.price_cents, "method": method.value, "quote_id": quote_id}, now,
        )
        session.flush()
        if self.dispatcher is not None:
            self.dispatcher.offer_next(session, ride.ride_id, now)
        return repo.get_ride(session, ride.ride_id)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/infra/test_factor_store.py tests/services/test_quotes.py tests/services/test_ride_requests.py -v 2>&1 | tail -30`
Expected: todos passam.

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app tests && git commit -m "feat(services): preço dinâmico com cotação travada e pedido de corrida" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Procura e ofertas (uma moto por vez, com fila)

**Files:**
- Create: `server/app/services/dispatch.py`
- Modify: `server/app/db/queries.py`, `server/tests/helpers_db.py`
- Test: `server/tests/services/test_dispatch.py`

**Interfaces:**
- Consumes: `rank_candidates`, `RiderStatus`, `ReservationBook` (domínio) ou `RedisReservationBook`; `PaymentService.start_pix_charge`; `PositionStore`; `MapsProvider`; `fee_for_ride`; `offer_block_reason`, `can_receive_cash_offers`; `local_day_start`; `repositories` (`get_ride`, `save_ride`, `get_rider_account`, `get_ride_details`, `log_ride_event`); `RideOfferRow`.
- Produces:
  - Em `queries`: `RiderSnapshot(rider_id, available, account, active_ride_id, active_destination, queued_ride_id)`, `rider_snapshots(session, rider_ids) -> dict[str, RiderSnapshot]`, `get_pending_offer(session, ride_id, *, for_update=False) -> RideOfferRow | None`, `offered_rider_ids(session, ride_id) -> set[str]`, `due_offer_ride_ids(session, now) -> list[str]`, `rider_active_ride_id(session, rider_id) -> str | None`, `completed_rides_since(session, rider_id, since) -> int`.
  - `Reservations` (Protocol: `reserve(rider_id, ride_id) -> bool`, `release(rider_id, ride_id) -> None`) e `OfferGone(Exception)`.
  - `DispatchService(positions, reservations, maps, payments, events, cfg=None)` com `offer_next(session, ride_id, now) -> str | None`, `accept_offer(session, rider_id, ride_id, now) -> Ride`, `decline_offer(session, rider_id, ride_id, now) -> str | None`, `expire_offers(session, now) -> int`.
  - Avisos emitidos: para o motoqueiro `offer` (dados da corrida), `offer_expired`, `ride_assigned`; para o passageiro `rider_accepted` (ficha do motoqueiro, código de 4 dígitos, se está na fila e, no Pix, a cobrança a pagar).

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `server/tests/helpers_db.py`:

```python
def add_completed_rides_today(session, rider_id: str, n: int, now: float, passenger_id: str = "p1") -> None:
    """`n` corridas concluídas hoje (nos últimos minutos antes de `now`) para contar a faixa de taxa do dia."""
    from app.db.models import RideRow

    for i in range(n):
        session.add(
            RideRow(
                id=f"done-{rider_id}-{i}", passenger_id=passenger_id, rider_id=rider_id, price_cents=700,
                payment_method="pix", pin="4821", state="completed", completed_at=now - 60 * (i + 1),
            )
        )
    session.flush()
```

`server/tests/services/test_dispatch.py`:

```python
import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.models import RideOfferRow
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore, RedisReservationBook
from app.services.dispatch import DispatchService, OfferGone
from app.services.events import EventCollector
from app.services.payments import PaymentService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import (
    add_accepted_ride,
    add_completed_rides_today,
    add_passenger,
    add_searching_ride,
    make_online_rider,
)

AGORA = 1_800_000_000.0


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def reservas():
    return ReservationBook()


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def dispatch(positions, reservas, provider, events):
    return DispatchService(positions, reservas, FakeMaps(), PaymentService(provider), events)


def tipos(events, user_id=None):
    return [e.type for e in events.events if user_id is None or e.user_id == user_id]


def mundo(session, positions, n_motos=2, method=PaymentMethod.PIX):
    add_passenger(session)
    riders = [make_online_rider(session, positions, n, pt(200 * n, 0), now=AGORA) for n in range(1, n_motos + 1)]
    add_searching_ride(session, method=method, now=AGORA)
    return riders


def test_oferta_vai_para_a_moto_mais_perto_e_avisa_o_motoqueiro(dispatch, session, positions, events):
    mundo(session, positions)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    oferta = session.query(RideOfferRow).one()
    assert (oferta.rider_id, oferta.status, oferta.will_queue) == ("r1", "pending", False)
    assert oferta.expires_at == AGORA + 15
    aviso = next(e for e in events.events if e.type == "offer")
    assert aviso.user_id == "r1" and aviso.payload["ride_id"] == "ride-1"
    assert aviso.payload["price_cents"] == 700 and aviso.payload["payment_method"] == "pix"
    assert aviso.payload["expires_at"] == AGORA + 15


def test_sem_motos_por_perto_nao_ha_oferta(dispatch, session, positions):
    add_passenger(session)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    make_online_rider(session, positions, 1, pt(9000, 0), now=AGORA)  # fora do raio de 3 km
    assert dispatch.offer_next(session, "ride-1", AGORA) is None


def test_moto_offline_bloqueada_ou_com_posicao_velha_nao_recebe(dispatch, session, positions):
    from app.db.models import RiderProfileRow, UserRow

    mundo(session, positions, n_motos=4)
    session.get(RiderProfileRow, "r1").online = False
    session.get(UserRow, "r2").is_blocked = True
    positions.update("r3", pt(600, 0), now=AGORA - 100)
    session.flush()
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r4"


def test_oferta_repetida_devolve_a_mesma_enquanto_nao_vence(dispatch, session, positions):
    mundo(session, positions)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert dispatch.offer_next(session, "ride-1", AGORA + 5) == "r1"
    assert session.query(RideOfferRow).count() == 1


def test_a_mesma_moto_nunca_recebe_dois_pedidos_ao_mesmo_tempo(dispatch, session, positions):
    # Review Focus 2
    mundo(session, positions, n_motos=1)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert dispatch.offer_next(session, "ride-2", AGORA) is None


def test_recusa_passa_para_a_proxima_e_quem_recusou_nao_recebe_de_novo(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    assert dispatch.decline_offer(session, "r1", "ride-1", AGORA + 3) == "r2"
    assert dispatch.decline_offer(session, "r2", "ride-1", AGORA + 6) is None
    assert dispatch.offer_next(session, "ride-1", AGORA + 7) is None
    estados = {o.rider_id: o.status for o in session.query(RideOfferRow)}
    assert estados == {"r1": "declined", "r2": "declined"}


def test_recusar_oferta_que_nao_e_sua_da_erro(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    with pytest.raises(OfferGone):
        dispatch.decline_offer(session, "r2", "ride-1", AGORA + 1)


def test_oferta_vencida_vira_expirada_e_a_proxima_moto_recebe(dispatch, session, positions, events):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    assert dispatch.expire_offers(session, AGORA + 14) == 0
    assert dispatch.expire_offers(session, AGORA + 16) == 1
    estados = {o.rider_id: o.status for o in session.query(RideOfferRow)}
    assert estados == {"r1": "expired", "r2": "pending"}
    assert "offer_expired" in tipos(events, "r1")


def test_aceitar_oferta_vencida_ou_de_outro_motoqueiro_ou_duas_vezes_da_erro(dispatch, session, positions):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r2", "ride-1", AGORA + 1)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 15)
    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    with pytest.raises(OfferGone):
        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 3)


def test_aceitar_corrida_pix_cria_a_cobranca_e_avisa_o_passageiro(dispatch, session, positions, events, reservas):
    mundo(session, positions)
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    assert ride.state is RideState.ACCEPTED and ride.rider_id == "r1" and ride.fee_cents == 100
    assert ride.pix_charge_created_at == AGORA + 4
    assert repo.get_current_charge_id(session, "ride-1") is not None
    assert session.query(RideOfferRow).one().status == "accepted"
    assert reservas.reserve("r1", "ride-outra") is True  # a reserva foi liberada
    aviso = next(e for e in events.events if e.type == "rider_accepted")
    assert aviso.user_id == "p1"
    assert aviso.payload["pin"] == "4821" and aviso.payload["queued"] is False
    assert aviso.payload["rider"]["plate"] == "ABC0001"
    assert aviso.payload["pay"]["amount_cents"] == 700
    assert "ride_assigned" in tipos(events, "r1")
    assert [k for k, _ in repo.ride_events(session, "ride-1")] == ["offered", "accepted"]


def test_aceitar_corrida_em_dinheiro_nao_cria_cobranca(dispatch, session, positions, events):
    mundo(session, positions, method=PaymentMethod.CASH)
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 4)
    assert ride.state is RideState.ACCEPTED
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert next(e for e in events.events if e.type == "rider_accepted").payload["pay"] is None


def test_taxa_depende_de_quantas_corridas_o_motoqueiro_ja_fez_hoje(dispatch, session, positions):
    mundo(session, positions, n_motos=1)
    add_completed_rides_today(session, "r1", 5, AGORA)
    from app.db.models import RideRow  # corrida de dois dias atrás não conta

    session.add(RideRow(id="velha", passenger_id="p1", rider_id="r1", price_cents=700, payment_method="pix",
                        pin="4821", state="completed", completed_at=AGORA - 2 * 86400))
    session.flush()
    dispatch.offer_next(session, "ride-1", AGORA)
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 1)
    assert ride.fee_cents == 90  # é a 6ª do dia: faixa de R$ 0,90


def _moto_terminando(session, positions, n=1):
    """Motoqueiro com uma corrida em andamento cujo destino está a 200 m do ponto de partida do novo pedido."""
    rider = make_online_rider(session, positions, n, pt(100, 0), now=AGORA)
    add_passenger(session, "p0", "+5575900000010")
    add_accepted_ride(session, ride_id="ride-0", passenger_id="p0", rider_id=rider)
    repo.set_ride_details(
        session, "ride-0",
        repo.RideDetails(pt(-2000, 0), pt(300, 0), "Origem", "Destino", 2300, 1.0, ""),
    )
    return rider


def test_moto_terminando_recebe_pedido_para_a_fila(dispatch, session, positions, events):
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == "r1"
    assert session.query(RideOfferRow).filter_by(ride_id="ride-1").one().will_queue is True
    ride = dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
    assert ride.state is RideState.QUEUED and ride.queued_since == AGORA + 2
    assert repo.get_current_charge_id(session, "ride-1") is not None  # o Pix nasce ao aceitar a da fila
    assert next(e for e in events.events if e.type == "rider_accepted").payload["queued"] is True


def test_moto_que_ja_tem_corrida_na_fila_nao_recebe_outra(dispatch, session, positions):
    add_passenger(session)
    _moto_terminando(session, positions)
    add_searching_ride(session, "ride-1", now=AGORA)
    dispatch.offer_next(session, "ride-1", AGORA)
    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 1)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    assert dispatch.offer_next(session, "ride-2", AGORA + 2) is None


def test_moto_na_10a_corrida_sem_entrada_nao_recebe_pedido_para_a_fila(dispatch, session, positions):
    # Review Focus 3 (lado da procura): a 11ª corrida não pode nascer para quem não pagou a entrada.
    add_passenger(session)
    rider = _moto_terminando(session, positions)
    acc = repo.get_rider_account(session, rider)
    acc.completed_rides = 9           # a corrida em andamento é a 10ª
    repo.save_rider_account(session, acc)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    acc.entry_paid = True
    repo.save_rider_account(session, acc)
    assert dispatch.offer_next(session, "ride-1", AGORA) == rider


def test_motoqueiro_na_10a_corrida_livre_ainda_recebe_a_10a(dispatch, session, positions):
    add_passenger(session)
    rider = make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    acc = repo.get_rider_account(session, rider)
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    add_searching_ride(session, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) == rider


def test_divida_de_corridas_em_dinheiro_no_limite_so_recebe_pix(dispatch, session, positions):
    add_passenger(session)
    rider = make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    acc = repo.get_rider_account(session, rider)
    acc.cash_debt_cents = 1000
    repo.save_rider_account(session, acc)
    add_searching_ride(session, "ride-1", method=PaymentMethod.CASH, now=AGORA)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-2", "p2", method=PaymentMethod.PIX, now=AGORA)
    assert dispatch.offer_next(session, "ride-2", AGORA) == rider


def test_com_reserva_no_redis_a_moto_tambem_nao_recebe_dois_pedidos(session, positions, provider, events, redis_client):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-1", now=AGORA)
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    servico = DispatchService(
        positions, RedisReservationBook(redis_client, ttl_ms=20_000), FakeMaps(), PaymentService(provider), events
    )
    assert servico.offer_next(session, "ride-1", AGORA) == "r1"
    assert servico.offer_next(session, "ride-2", AGORA) is None
    servico.decline_offer(session, "r1", "ride-1", AGORA + 1)
    assert servico.offer_next(session, "ride-2", AGORA + 2) == "r1"


def test_so_oferece_corrida_que_ainda_esta_em_procura(dispatch, session, positions):
    mundo(session, positions)
    ride = repo.get_ride(session, "ride-1")
    ride.state = RideState.CANCELLED
    repo.save_ride(session, ride)
    assert dispatch.offer_next(session, "ride-1", AGORA) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_dispatch.py -q 2>&1 | tail -6`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.services.dispatch'`.

- [ ] **Step 3: Implementar**

Em `server/app/db/queries.py`, acrescentar às importações `from app.db.models import RideOfferRow`, `from app.domain.fees import RiderAccount`, `from app.domain.geo import GeoPoint`; e no fim:

```python


@dataclass(frozen=True)
class RiderSnapshot:
    rider_id: str
    available: bool                         # aprovado, disponível e sem bloqueio
    account: RiderAccount
    active_ride_id: str | None
    active_destination: GeoPoint | None
    queued_ride_id: str | None


def rider_snapshots(session: Session, rider_ids: list[str]) -> dict[str, RiderSnapshot]:
    if not rider_ids:
        return {}
    profiles = session.execute(
        select(RiderProfileRow, UserRow.is_blocked)
        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
        .where(RiderProfileRow.user_id.in_(rider_ids))
    ).all()
    active = {
        r.rider_id: r
        for r in session.execute(
            select(RideRow).where(RideRow.rider_id.in_(rider_ids), RideRow.state.in_(_ACTIVE))
        ).scalars()
    }
    queued = {
        r.rider_id: r.id
        for r in session.execute(
            select(RideRow).where(RideRow.rider_id.in_(rider_ids), RideRow.state == RideState.QUEUED.value)
        ).scalars()
    }
    snapshots: dict[str, RiderSnapshot] = {}
    for profile, blocked in profiles:
        ride = active.get(profile.user_id)
        snapshots[profile.user_id] = RiderSnapshot(
            rider_id=profile.user_id,
            available=bool(profile.online and profile.status == "approved" and not blocked),
            account=RiderAccount(
                rider_id=profile.user_id, completed_rides=profile.completed_rides, entry_paid=profile.entry_paid,
                cash_debt_cents=profile.cash_debt_cents, debt_reserved_cents=profile.debt_reserved_cents,
            ),
            active_ride_id=ride.id if ride else None,
            active_destination=GeoPoint(ride.dest_lat, ride.dest_lng) if ride and ride.dest_lat is not None else None,
            queued_ride_id=queued.get(profile.user_id),
        )
    return snapshots


def get_pending_offer(session: Session, ride_id: str, *, for_update: bool = False) -> RideOfferRow | None:
    stmt = select(RideOfferRow).where(RideOfferRow.ride_id == ride_id, RideOfferRow.status == "pending")
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def offered_rider_ids(session: Session, ride_id: str) -> set[str]:
    """Quem já recebeu oferta deste pedido (aceitou, recusou ou deixou vencer): não recebe de novo."""
    return set(session.execute(select(RideOfferRow.rider_id).where(RideOfferRow.ride_id == ride_id)).scalars())


def due_offer_ride_ids(session: Session, now: float) -> list[str]:
    return list(
        session.execute(
            select(RideOfferRow.ride_id)
            .where(RideOfferRow.status == "pending", RideOfferRow.expires_at <= now)
            .order_by(RideOfferRow.id)
        ).scalars()
    )


def rider_active_ride_id(session: Session, rider_id: str) -> str | None:
    return session.execute(
        select(RideRow.id).where(RideRow.rider_id == rider_id, RideRow.state.in_(_ACTIVE)).limit(1)
    ).scalar_one_or_none()


def completed_rides_since(session: Session, rider_id: str, since: float) -> int:
    return session.execute(
        select(func.count()).select_from(RideRow).where(
            RideRow.rider_id == rider_id, RideRow.state == RideState.COMPLETED.value, RideRow.completed_at >= since
        )
    ).scalar_one()
```

`server/app/services/dispatch.py`:

```python
"""Procura da moto e ofertas, uma por vez (spec, seções 5.1, 5.2 e 12)."""
from __future__ import annotations

import dataclasses
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RideOfferRow
from app.domain.clock import local_day_start
from app.domain.dispatch import RiderStatus, rank_candidates
from app.domain.fees import can_receive_cash_offers, fee_for_ride, offer_block_reason
from app.domain.maps import MapsProvider
from app.domain.rides import Ride, RideState, accept
from app.domain.types import PaymentMethod
from app.infra.redis_store import PositionStore
from app.services.events import EventCollector
from app.services.payments import PaymentService


class OfferGone(Exception):
    """A oferta não existe mais para este motoqueiro (venceu, foi para outro, ou a corrida mudou)."""


class Reservations(Protocol):
    def reserve(self, rider_id: str, ride_id: str) -> bool: ...

    def release(self, rider_id: str, ride_id: str) -> None: ...


class DispatchService:
    def __init__(
        self,
        positions: PositionStore,
        reservations: Reservations,
        maps: MapsProvider,
        payments: PaymentService,
        events: EventCollector,
        cfg: AppConfig | None = None,
    ) -> None:
        self.positions = positions
        self.reservations = reservations
        self.maps = maps
        self.payments = payments
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    # --- procura ---------------------------------------------------------------------

    def _statuses(self, session: Session, ride: Ride, near: list) -> list[RiderStatus]:
        snapshots = queries.rider_snapshots(session, [rider_id for rider_id, _ in near])
        statuses: list[RiderStatus] = []
        for rider_id, point in near:
            snap = snapshots.get(rider_id)
            if snap is None or not snap.available:
                continue
            busy = snap.active_ride_id is not None
            # a corrida que ele está fazendo conta para a entrada: a 10ª corrida em andamento já fecha o teste
            gate = dataclasses.replace(snap.account, completed_rides=snap.account.completed_rides + (1 if busy else 0))
            if offer_block_reason(gate, self.cfg.fees) is not None:
                continue
            if ride.payment_method is PaymentMethod.CASH and not can_receive_cash_offers(gate, self.cfg.fees):
                continue
            seconds = (
                self.maps.eta_seconds(point, snap.active_destination) if busy and snap.active_destination else None
            )
            statuses.append(
                RiderStatus(
                    rider_id, point, True, snap.active_ride_id, snap.queued_ride_id, seconds, snap.active_destination
                )
            )
        return statuses

    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None:
        """Oferece o pedido à próxima moto. Devolve o motoqueiro com oferta pendente, ou None."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.SEARCHING:
            return None
        pending = queries.get_pending_offer(session, ride_id, for_update=True)
        if pending is not None:
            if pending.expires_at > now:
                return pending.rider_id
            pending.status = "expired"
            session.flush()
            self.reservations.release(pending.rider_id, ride_id)
            self.events.add(pending.rider_id, "offer_expired", {"ride_id": ride_id})
        details = repo.get_ride_details(session, ride_id)
        dispatch_cfg = self.cfg.dispatch
        near = self.positions.nearby(details.pickup, dispatch_cfg.search_radius_m, now, dispatch_cfg.position_max_age_s)
        declined = queries.offered_rider_ids(session, ride_id)
        statuses = [s for s in self._statuses(session, ride, near) if s.rider_id not in declined]
        for candidate in rank_candidates(statuses, details.pickup, self.maps, dispatch_cfg):
            if not self.reservations.reserve(candidate.rider_id, ride_id):
                continue
            try:
                with session.begin_nested():
                    session.add(
                        RideOfferRow(
                            ride_id=ride_id, rider_id=candidate.rider_id, status="pending",
                            will_queue=candidate.will_queue, created_at=now, expires_at=now + dispatch_cfg.offer_timeout_s,
                        )
                    )
                    session.flush()
            except IntegrityError:
                self.reservations.release(candidate.rider_id, ride_id)
                continue
            repo.log_ride_event(session, ride_id, "offered", {"rider_id": candidate.rider_id}, now)
            self.events.add(
                candidate.rider_id, "offer",
                {
                    "ride_id": ride_id, "price_cents": ride.price_cents, "payment_method": ride.payment_method.value,
                    "pickup": {"lat": details.pickup.lat, "lng": details.pickup.lng, "text": details.pickup_text},
                    "destination": {
                        "lat": details.destination.lat, "lng": details.destination.lng, "text": details.destination_text,
                    },
                    "distance_m": details.distance_m, "seconds_to_pickup": candidate.eta_seconds,
                    "will_queue": candidate.will_queue, "expires_at": now + dispatch_cfg.offer_timeout_s,
                },
            )
            return candidate.rider_id
        return None

    # --- resposta do motoqueiro ----------------------------------------------------------

    def accept_offer(self, session: Session, rider_id: str, ride_id: str, now: float) -> Ride:
        ride = repo.get_ride(session, ride_id, for_update=True)
        offer = queries.get_pending_offer(session, ride_id, for_update=True)
        if (
            ride.state is not RideState.SEARCHING
            or offer is None
            or offer.rider_id != rider_id
            or offer.expires_at <= now
        ):
            raise OfferGone("Essa corrida já foi para outro motoqueiro.")
        repo.get_rider_account(session, rider_id, for_update=True)
        busy = queries.rider_active_ride_id(session, rider_id) is not None
        number = queries.completed_rides_since(session, rider_id, local_day_start(now)) + (1 if busy else 0) + 1
        fee = fee_for_ride(number, self.cfg.fees)
        accept(ride, rider_id, now, rider_busy=busy)
        ride.fee_cents = fee
        repo.save_ride(session, ride)
        offer.status = "accepted"
        session.flush()
        self.reservations.release(rider_id, ride_id)
        charge = self.payments.start_pix_charge(session, ride_id, fee) if ride.payment_method is PaymentMethod.PIX else None
        repo.log_ride_event(session, ride_id, "accepted", {"rider_id": rider_id, "queued": busy, "fee_cents": fee}, now)
        card = queries.rider_card(session, rider_id)
        self.events.add(rider_id, "ride_assigned", {"ride_id": ride_id, "queued": busy})
        self.events.add(
            ride.passenger_id, "rider_accepted",
            {
                "ride_id": ride_id, "queued": busy, "pin": ride.pin,
                "rider": dataclasses.asdict(card),
                "pay": None if charge is None else {
                    "charge_id": charge.charge_id, "amount_cents": charge.amount_cents,
                    "expires_at": now + self.cfg.rides.pix_window_s,
                },
            },
        )
        return repo.get_ride(session, ride_id)

    def decline_offer(self, session: Session, rider_id: str, ride_id: str, now: float) -> str | None:
        repo.get_ride(session, ride_id, for_update=True)
        offer = queries.get_pending_offer(session, ride_id, for_update=True)
        if offer is None or offer.rider_id != rider_id:
            raise OfferGone("Essa corrida já foi para outro motoqueiro.")
        offer.status = "declined"
        session.flush()
        self.reservations.release(rider_id, ride_id)
        repo.log_ride_event(session, ride_id, "declined", {"rider_id": rider_id}, now)
        return self.offer_next(session, ride_id, now)

    def expire_offers(self, session: Session, now: float) -> int:
        """Ofertas que passaram dos 15 segundos: expira e oferece à próxima moto. Devolve quantas venceram."""
        due = queries.due_offer_ride_ids(session, now)
        for ride_id in due:
            self.offer_next(session, ride_id, now)
        return len(due)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_dispatch.py -v 2>&1 | tail -40`
Expected: todos passam (19 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app tests && git commit -m "feat(services): procura da moto, ofertas uma por vez, aceite, recusa e fila" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dinheiro do fim da corrida em dinheiro e taxa de entrada

**Files:**
- Modify: `server/app/services/payments.py`, `server/app/db/repositories.py`, `server/tests/helpers_db.py`
- Test: `server/tests/services/test_payment_end_flow.py`

**Interfaces:**
- Consumes: tudo do `PaymentService` do plano 2A (`_rider_and_charge`, `_refund`, `_release_if_reserved`); `cash_pay_wait_expired`, `block_for_unpaid`, `confirm_qr_payment`, `confirm_end_payment`, `settle_passenger_debt` (domínio); `add_cash_fee_debt`, `mark_entry_paid`; `EventCollector`.
- Produces:
  - `PaymentService(provider, fee_cfg=None, ride_cfg=None, events=None)` (o quarto parâmetro é novo e opcional).
  - `start_end_charge(session, ride_id, fee_cents) -> PixCharge` (corrida em dinheiro concluída; cria o QR do fim, finalidade `end`; chamar de novo devolve a mesma).
  - `confirm_cash_received(session, ride_id, now) -> None` (o motoqueiro recebeu em dinheiro: a taxa vira dívida dele e a reserva de dívida do QR é solta).
  - `block_unpaid_cash_ride(session, ride_id, now) -> bool` (passou `cash_pay_wait_s`: bloqueia o passageiro; **sem** taxa para o motoqueiro).
  - `start_entry_charge(session, rider_id) -> PixCharge` (R$ 50, finalidade `entry`, sem corrida; chamar de novo devolve a aberta).
  - `on_provider_event` passa a tratar as três finalidades (`ride`, `end`, `entry`) e devolve `"applied"`, `"refunded"` ou `"duplicate"` como antes.
  - Em `repositories`: `find_open_entry_charge(session, rider_id) -> PixCharge | None`.
  - Em `tests/helpers_db.py`: `add_completed_ride(session, ride_id="ride-1", passenger_id="p1", rider_id="r1", method=PaymentMethod.CASH, price=700, fee=100, completed_at=1000.0) -> Ride`.
  - Avisos (quando `events` foi dado): `payment_received` (motoqueiro), `unblocked` e `payment_confirmed` e `payment_pending` (passageiro), `passenger_blocked` (motoqueiro), `entry_paid` (motoqueiro).

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `server/tests/helpers_db.py` (e, nas importações do topo, `complete, confirm_helmet, mark_arrived, start_ride` de `app.domain.rides`):

```python
def add_completed_ride(
    session,
    ride_id: str = "ride-1",
    passenger_id: str = "p1",
    rider_id: str = "r1",
    method: PaymentMethod = PaymentMethod.CASH,
    price: int = 700,
    fee: int = 100,
    completed_at: float = 1000.0,
) -> Ride:
    """Corrida que já terminou. A taxa decidida no aceite fica em `fee_cents`."""
    ride = Ride(ride_id, passenger_id, price, method, pin="4821")
    start_search(ride, 0)
    accept(ride, rider_id, 1, rider_busy=False)
    mark_arrived(ride, 2)
    confirm_helmet(ride)
    if method is PaymentMethod.PIX:
        ride.pix_paid = True
    start_ride(ride, "4821")
    complete(ride, completed_at)
    ride.fee_cents = fee
    repo.add_ride(session, ride)
    return ride
```

`server/tests/services/test_payment_end_flow.py`:

```python
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import DebtState
from app.domain.rides import InvalidTransition
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import passenger_block_reason
from tests.helpers_db import add_completed_ride, add_passenger, add_rider

FEE = 100
FIM = 1000.0  # instante em que a corrida terminou


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def service(provider, events):
    return PaymentService(provider, events=events)


def mundo(session, debt=0, method=PaymentMethod.CASH):
    add_passenger(session)
    add_rider(session, debt_cents=debt)
    return add_completed_ride(session, method=method, fee=FEE, completed_at=FIM)


def divida(session):
    acc = repo.get_rider_account(session, "r1")
    return acc.cash_debt_cents, acc.debt_reserved_cents


def pendente(session):
    return repo.get_passenger_account(session, "p1").unpaid_cents


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_qr_do_fim_nasce_com_a_divisao_e_reserva_a_divida(session, service):
    mundo(session, debt=400)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert charge.purpose == "end" and charge.amount_cents == 700
    assert charge.split.debt_paid_cents == 300 and charge.split.company_cents == 400
    assert repo.get_current_charge_id(session, "ride-1") == charge.charge_id
    assert divida(session) == (400, 300)
    assert service.start_end_charge(session, "ride-1", FEE).charge_id == charge.charge_id


def test_qr_so_para_corrida_em_dinheiro_ja_concluida_e_nao_paga(session, service):
    mundo(session, method=PaymentMethod.PIX)
    with pytest.raises(InvalidTransition, match="dinheiro"):
        service.start_end_charge(session, "ride-1", FEE)


def test_pago_pelo_qr_dentro_do_prazo_divide_e_abate_a_divida(session, service, provider, events):
    # Review Focus 1
    mundo(session, debt=1000)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    assert divida(session) == (700, 0)
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (300, 400, -700)
    assert ledger.is_balanced() is True
    assert pendente(session) == 0
    assert "payment_received" in tipos(events, "r1")


def test_motoqueiro_confirma_dinheiro_a_taxa_vira_divida_e_a_reserva_solta(session, service, events):
    mundo(session, debt=400)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.confirm_cash_received(session, "ride-1", now=FIM + 30)
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    assert divida(session) == (500, 0)   # 400 antigos + R$ 1,00 desta corrida; reserva solta
    assert repo.get_charge(session, charge.charge_id).debt_state is DebtState.RELEASED
    assert pendente(session) == 0
    assert "payment_confirmed" in tipos(events, "p1")


def test_confirmar_dinheiro_duas_vezes_da_erro(session, service):
    mundo(session)
    service.confirm_cash_received(session, "ride-1", now=FIM + 5)
    with pytest.raises(InvalidTransition, match="já foi confirmado"):
        service.confirm_cash_received(session, "ride-1", now=FIM + 6)


def test_qr_pago_depois_de_o_motoqueiro_confirmar_dinheiro_e_devolvido(session, service, provider):
    # Review Focus 1: o passageiro pagou duas vezes (dinheiro e QR).
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.confirm_cash_received(session, "ride-1", now=FIM + 5)
    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
    assert provider.charges[charge.charge_id].refunded is True
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (0, 0, 0)
    assert divida(session) == (100, 0)   # só a taxa do dinheiro vivo que ele recebeu


def test_prazo_vencido_bloqueia_o_passageiro_sem_cobrar_taxa_do_motoqueiro(session, service, events):
    # Review Focus 1
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 299) is False
    assert pendente(session) == 0
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 300) is True
    assert pendente(session) == 700
    assert repo.get_ride(session, "ride-1").non_payment_reported is True
    assert divida(session) == (0, 0)
    assert "Falta pagar" in passenger_block_reason(session, "p1")
    assert tipos(events, "r1") == ["passenger_blocked"]
    pendente_aviso = next(e for e in events.events if e.type == "payment_pending")
    assert pendente_aviso.user_id == "p1" and pendente_aviso.payload["charge_id"] == charge.charge_id
    assert service.block_unpaid_cash_ride(session, "ride-1", FIM + 400) is False  # só uma vez


def test_motoqueiro_nao_confirma_dinheiro_depois_do_bloqueio(session, service):
    # Review Focus 1
    mundo(session)
    service.start_end_charge(session, "ride-1", FEE)
    service.block_unpaid_cash_ride(session, "ride-1", FIM + 300)
    with pytest.raises(InvalidTransition, match="Pix"):
        service.confirm_cash_received(session, "ride-1", now=FIM + 310)


def test_pagamento_atrasado_desbloqueia_o_passageiro_e_paga_o_motoqueiro_uma_vez(session, service, provider, events):
    # Review Focus 1
    mundo(session)
    charge = service.start_end_charge(session, "ride-1", FEE)
    service.block_unpaid_cash_ride(session, "ride-1", FIM + 300)
    evento = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, evento) == "applied"
    assert pendente(session) == 0
    assert passenger_block_reason(session, "p1") is None
    assert repo.get_ride(session, "ride-1").end_payment_confirmed is True
    ledger = PgLedger(session)
    assert (ledger.balance("rider:r1"), ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (600, 100, -700)
    assert divida(session) == (0, 0)
    assert "unblocked" in tipos(events, "p1") and "payment_received" in tipos(events, "r1")
    assert service.on_provider_event(session, evento) == "duplicate"
    assert ledger.balance("rider:r1") == 600


def test_entrada_de_50_reais_cria_cobranca_sem_corrida_e_paga_uma_vez(session, service, provider, events):
    add_rider(session)
    charge = service.start_entry_charge(session, "r1")
    assert (charge.purpose, charge.ride_id, charge.amount_cents) == ("entry", "", 5000)
    assert (charge.split.rider_cents, charge.split.company_cents) == (0, 5000)
    assert service.start_entry_charge(session, "r1").charge_id == charge.charge_id
    evento = provider.mark_paid(charge.charge_id)
    assert service.on_provider_event(session, evento) == "applied"
    assert repo.get_rider_account(session, "r1").entry_paid is True
    ledger = PgLedger(session)
    assert (ledger.balance(PgLedger.COMPANY), ledger.balance(PgLedger.PROVIDER)) == (5000, -5000)
    assert ledger.is_balanced() is True
    assert service.on_provider_event(session, evento) == "duplicate"
    assert service.on_provider_event(session, {**evento, "event_id": "evt-outro"}) == "duplicate"
    assert ledger.balance(PgLedger.COMPANY) == 5000
    assert tipos(events, "r1") == ["entry_paid"]
    with pytest.raises(InvalidTransition, match="já foi paga"):
        service.start_entry_charge(session, "r1")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_payment_end_flow.py -q 2>&1 | tail -6`
Expected: falhas `AttributeError: 'PaymentService' object has no attribute 'start_end_charge'` (e `TypeError ... unexpected keyword argument 'events'`).

- [ ] **Step 3: Implementar**

Em `server/app/db/repositories.py`, acrescentar no fim:

```python


def find_open_entry_charge(session: Session, rider_id: str) -> PixCharge | None:
    """Cobrança da entrada de R$ 50 que o motoqueiro ainda não pagou, se houver."""
    row = session.execute(
        select(PixChargeRow)
        .where(PixChargeRow.rider_id == rider_id, PixChargeRow.purpose == "entry", PixChargeRow.paid.is_(False))
        .limit(1)
    ).scalar_one_or_none()
    return _charge_to_domain(row) if row is not None else None
```

Em `server/app/services/payments.py`:

(a) trocar o bloco de importações (do `from __future__` até `from app.domain.types import PaymentMethod`) por:

```python
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.config import FeeConfig, RideConfig
from app.domain.fees import RiderAccount, add_cash_fee_debt, mark_entry_paid
from app.domain.payments import (
    DebtState,
    PaymentProvider,
    PixCharge,
    Split,
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
    block_for_unpaid,
    cancel,
    cancel_after_arrival_timeout,
    cancel_unpaid_pix,
    cash_pay_wait_expired,
    confirm_end_payment,
    confirm_qr_payment,
    on_pix_paid,
    pix_window_expired,
    release_from_queue,
    settle_passenger_debt,
)
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
```

(b) trocar o `__init__` e acrescentar `_emit` logo depois dele:

```python
    def __init__(
        self,
        provider: PaymentProvider,
        fee_cfg: FeeConfig | None = None,
        ride_cfg: RideConfig | None = None,
        events: EventCollector | None = None,
    ) -> None:
        self.provider = provider
        self.fee_cfg = fee_cfg or FeeConfig()
        self.ride_cfg = ride_cfg or RideConfig()
        self.events = events

    def _emit(self, user_id: str | None, type: str, payload: dict | None = None) -> None:
        if self.events is not None and user_id is not None:
            self.events.add(user_id, type, payload)
```

(c) trocar o método `on_provider_event` inteiro por estes três métodos:

```python
    def on_provider_event(self, session: Session, event: dict) -> str:
        """Trata o aviso de "pago" do provedor. Devolve "applied", "refunded" ou "duplicate"."""
        if event.get("type") != "paid":
            raise ValueError(f"tipo de aviso desconhecido: {event.get('type')}")
        if not repo.first_time_event(session, event["event_id"]):
            return "duplicate"
        known = repo.get_charge(session, event["charge_id"])
        if known.purpose == "entry":
            return self._on_entry_paid(session, known)
        ride = repo.get_ride(session, known.ride_id, for_update=True)
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        ledger = PgLedger(session)
        ledger.post_charge_payment(charge.charge_id, charge.rider_id, charge.amount_cents, charge.split)
        is_current = repo.get_current_charge_id(session, ride.ride_id) == charge.charge_id
        if charge.purpose == "end":
            refund_needed = self._apply_end_payment(session, ride, acc, charge, is_current)
        else:
            refund_needed = on_pix_paid(ride) if is_current else True
            if not refund_needed:
                confirm_charge_debt(acc, charge)
        if refund_needed:
            self._refund(charge, acc, ledger)
            outcome = "refunded"
        else:
            outcome = "applied"
        repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        return outcome

    def _apply_end_payment(
        self, session: Session, ride: Ride, acc: RiderAccount, charge: PixCharge, is_current: bool
    ) -> bool:
        """Pix do QR do fim da corrida em dinheiro. Devolve True se o dinheiro deve voltar ao passageiro."""
        if not is_current or ride.state is not RideState.COMPLETED or ride.end_payment_confirmed:
            return True  # já foi pago em dinheiro (ou a cobrança é velha): o QR pago a mais volta
        was_blocked = ride.non_payment_reported
        if was_blocked:
            passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
            owed = min(passenger.unpaid_cents, ride.price_cents)
            if owed > 0:
                settle_passenger_debt(passenger, owed)
            repo.save_passenger_account(session, passenger)
        confirm_qr_payment(ride)
        confirm_charge_debt(acc, charge)
        self._emit(ride.rider_id, "payment_received", {"ride_id": ride.ride_id, "late": was_blocked})
        if was_blocked:
            self._emit(ride.passenger_id, "unblocked", {"ride_id": ride.ride_id})
        return False

    def _on_entry_paid(self, session: Session, known: PixCharge) -> str:
        acc = repo.get_rider_account(session, known.rider_id, for_update=True)
        charge = repo.get_charge(session, known.charge_id, for_update=True)
        if charge.paid:
            return "duplicate"
        charge.paid = True
        charge.debt_state = DebtState.APPLIED
        PgLedger(session).post_entry_fee(charge.rider_id, charge.amount_cents)
        mark_entry_paid(acc)
        repo.save_charge(session, charge)
        repo.save_rider_account(session, acc)
        self._emit(charge.rider_id, "entry_paid")
        return "applied"
```

(d) acrescentar no fim da classe `PaymentService`:

```python

    # --- fim de corrida em dinheiro e taxa de entrada --------------------------------------

    def start_end_charge(self, session: Session, ride_id: str, fee_cents: int) -> PixCharge:
        """No fim de uma corrida em dinheiro: cria o QR do Pix com o valor (spec, seção 7.2)."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if (
            ride.payment_method is not PaymentMethod.CASH
            or ride.state is not RideState.COMPLETED
            or ride.rider_id is None
        ):
            raise InvalidTransition("só dá para gerar o QR de uma corrida em dinheiro já concluída")
        if ride.end_payment_confirmed:
            raise InvalidTransition("o pagamento desta corrida já foi confirmado")
        existing_id = repo.get_current_charge_id(session, ride_id)
        if existing_id is not None:
            return repo.get_charge(session, existing_id)
        acc = repo.get_rider_account(session, ride.rider_id, for_update=True)
        split = reserve_pix_split(acc, ride.price_cents, fee_cents, self.fee_cfg.max_debt_share)
        charge = self.provider.create_pix_charge(ride.ride_id, ride.rider_id, ride.price_cents, split, purpose="end")
        repo.add_charge(session, charge)
        repo.set_current_charge(session, ride_id, charge.charge_id)
        repo.save_rider_account(session, acc)
        return charge

    def confirm_cash_received(self, session: Session, ride_id: str, now: float) -> None:
        """O motoqueiro recebeu o dinheiro na mão: a taxa da corrida vira dívida dele."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
            raise InvalidTransition("só dá para confirmar o pagamento de uma corrida em dinheiro já concluída")
        if ride.end_payment_confirmed:
            raise InvalidTransition("o pagamento desta corrida já foi confirmado")
        if ride.non_payment_reported:
            raise InvalidTransition(
                "o passageiro está com o pagamento pendente: ele paga pelo Pix e o valor cai na sua conta"
            )
        confirm_end_payment(ride)
        acc, charge = self._rider_and_charge(session, ride)
        self._release_if_reserved(charge, acc)
        if acc is not None:
            add_cash_fee_debt(acc, ride.fee_cents or 0)
            repo.save_rider_account(session, acc)
        if charge is not None:
            repo.save_charge(session, charge)
        repo.save_ride(session, ride)
        self._emit(ride.passenger_id, "payment_confirmed", {"ride_id": ride_id})

    def block_unpaid_cash_ride(self, session: Session, ride_id: str, now: float) -> bool:
        """Passou `cash_pay_wait_s` sem pagamento: bloqueia o passageiro. O motoqueiro não deve taxa."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if not cash_pay_wait_expired(ride, now, self.ride_cfg):
            return False
        passenger = repo.get_passenger_account(session, ride.passenger_id, for_update=True)
        block_for_unpaid(ride, passenger, now, self.ride_cfg)
        repo.save_ride(session, ride)
        repo.save_passenger_account(session, passenger)
        self._emit(ride.rider_id, "passenger_blocked", {"ride_id": ride_id})
        self._emit(
            ride.passenger_id, "payment_pending",
            {
                "ride_id": ride_id, "amount_cents": ride.price_cents,
                "charge_id": repo.get_current_charge_id(session, ride_id),
            },
        )
        return True

    def start_entry_charge(self, session: Session, rider_id: str) -> PixCharge:
        """Cobrança da entrada de R$ 50 (uma vez só, depois das corridas de teste)."""
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        if acc.entry_paid:
            raise InvalidTransition("a entrada já foi paga")
        open_charge = repo.find_open_entry_charge(session, rider_id)
        if open_charge is not None:
            return open_charge
        amount = self.fee_cfg.entry_fee_cents
        charge = self.provider.create_pix_charge("", rider_id, amount, Split(0, amount, 0), purpose="entry")
        repo.add_charge(session, charge)
        return charge
```

Nota de leitura do código: `cancel_after_arrival_timeout` do domínio e o método de mesmo nome do serviço já existem desde o plano 2A; a importação nova só acrescenta nomes que o arquivo ainda não usava.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_payment_end_flow.py -v 2>&1 | tail -20`
Expected: todos passam (10 testes).

Run: `.venv/bin/pytest tests/services -q`
Expected: os 18 testes do serviço de pagamentos do plano 2A e o cenário do dia continuam passando.

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app tests && git commit -m "feat(services): QR do fim da corrida em dinheiro, bloqueio automático por falta de pagamento e taxa de entrada" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Andamento da corrida, cancelamento, fila e avaliações

**Files:**
- Create: `server/app/services/trips.py`
- Modify: `server/app/services/dispatch.py` (acrescentar `withdraw_offer`), `server/app/db/queries.py`
- Test: `server/tests/services/test_trips.py`

**Interfaces:**
- Consumes: `PaymentService` (tarefas 7 e 2A: `cancel_ride`, `start_end_charge`, `confirm_cash_received`, `release_queued_ride`); `DispatchService` (tarefa 6); funções do domínio `mark_arrived`, `confirm_helmet`, `start_ride`, `complete`, `promote_from_queue`; `count_completed_ride`, `offer_block_reason`; `RatingRow`, `RiderProfileRow`.
- Produces:
  - Em `queries`: `queued_ride_id_of_rider(session, rider_id) -> str | None`.
  - Em `DispatchService`: `withdraw_offer(session, ride_id) -> None` (tira a oferta pendente de uma corrida que saiu da procura, solta a moto e avisa o motoqueiro com `offer_expired`).
  - `NotYourRide`, `AlreadyRated` (exceções); `TripService(payments, dispatcher, events, cfg=None)` com `arrive(session, rider_id, ride_id, now)`, `confirm_helmet(session, rider_id, ride_id, now)`, `start_trip(session, rider_id, ride_id, pin, now)`, `complete_trip(session, rider_id, ride_id, now)`, `confirm_cash_received(session, rider_id, ride_id, now)`, `cancel_by_passenger(session, passenger_id, ride_id, now) -> CancelResult`, `after_ride_ends(session, rider_id, now)` (promove a corrida da fila ou, se o motoqueiro não pode continuar, devolve a da fila para a busca), `rate(session, user_id, ride_id, stars, now)`.
  - Eventos do histórico da corrida (`ride_events`): `arrived`, `helmet_confirmed`, `started`, `completed`, `cancelled`, `queue_released`, `promoted`, `rated`.
  - Avisos: `rider_arrived`, `trip_started`, `trip_completed` (passageiro e motoqueiro; com o QR a pagar em corrida em dinheiro), `ride_cancelled`, `queue_released`, `rider_on_the_way`, `next_ride`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/services/test_trips.py`:

```python
import datetime as dt
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.models import RideOfferRow, RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.rides import CancelResult, InvalidTransition, RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.riders import CannotGoOnline, RiderService
from app.services.trips import AlreadyRated, NotYourRide, TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride, make_online_rider

AGORA = 1_800_000_000.0


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def reservas():
    return ReservationBook()


@pytest.fixture()
def w(positions, reservas, provider, events):
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, reservas, FakeMaps(), payments, events)
    return SimpleNamespace(
        payments=payments, dispatch=dispatch, trips=TripService(payments, dispatch, events), provider=provider
    )


def aceitar(session, positions, w, method=PaymentMethod.PIX, ride_id="ride-1", passenger_id="p1", rider_n=1,
            destination=None, now=AGORA):
    """Corrida pedida, oferecida e aceita pelo motoqueiro `r<rider_n>`."""
    rider_id = f"r{rider_n}"
    if session.get(RiderProfileRow, rider_id) is None:
        make_online_rider(session, positions, rider_n, pt(100 * rider_n, 0), now=now)
    add_searching_ride(session, ride_id, passenger_id, method=method, destination=destination, now=now)
    assert w.dispatch.offer_next(session, ride_id, now) == rider_id
    return w.dispatch.accept_offer(session, rider_id, ride_id, now + 4)


def pagar(session, w, ride_id="ride-1"):
    charge_id = repo.get_current_charge_id(session, ride_id)
    assert w.payments.on_provider_event(session, w.provider.mark_paid(charge_id)) == "applied"


def ate_o_fim(session, w, rider_id="r1", ride_id="ride-1", t=AGORA + 100):
    ride = repo.get_ride(session, ride_id)
    w.trips.arrive(session, rider_id, ride_id, t)
    w.trips.confirm_helmet(session, rider_id, ride_id, t + 1)
    w.trips.start_trip(session, rider_id, ride_id, ride.pin, t + 5)
    w.trips.complete_trip(session, rider_id, ride_id, t + 400)


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_corrida_pix_do_aceite_ao_fim(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w)
    pagar(session, w)
    ate_o_fim(session, w)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.COMPLETED and ride.completed_at == AGORA + 500
    assert repo.get_rider_account(session, "r1").completed_rides == 1
    assert [k for k, _ in repo.ride_events(session, "ride-1")] == [
        "offered", "accepted", "arrived", "helmet_confirmed", "started", "completed",
    ]
    fim = next(e for e in events.events if e.type == "trip_completed" and e.user_id == "p1")
    assert fim.payload["pay"] is None and fim.payload["price_cents"] == 700
    assert {"rider_arrived", "trip_started"} <= set(tipos(events, "p1"))


def test_nao_inicia_sem_capacete_sem_pix_ou_com_codigo_errado(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w)
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    with pytest.raises(InvalidTransition, match="capacete"):
        w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 51)
    w.trips.confirm_helmet(session, "r1", "ride-1", AGORA + 52)
    with pytest.raises(InvalidTransition, match="Pix"):
        w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 53)
    pagar(session, w)
    ride = repo.get_ride(session, "ride-1")
    assert ride.helmet_confirmed is True
    with pytest.raises(ValueError, match="código"):
        w.trips.start_trip(session, "r1", "ride-1", "0000", AGORA + 53)
    w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 54)
    assert repo.get_ride(session, "ride-1").state is RideState.IN_PROGRESS


def test_so_o_motoqueiro_da_corrida_mexe_nela(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w)
    make_online_rider(session, positions, 2, pt(900, 0), now=AGORA)
    with pytest.raises(NotYourRide):
        w.trips.arrive(session, "r2", "ride-1", AGORA + 50)
    with pytest.raises(NotYourRide):
        w.trips.cancel_by_passenger(session, "p-outro", "ride-1", AGORA + 50)


def test_corrida_em_dinheiro_ao_terminar_gera_o_qr_e_ainda_nao_cobra_taxa(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    charge = repo.get_charge(session, repo.get_current_charge_id(session, "ride-1"))
    assert charge.purpose == "end" and charge.amount_cents == 700
    for dono in ("p1", "r1"):
        aviso = next(e for e in events.events if e.type == "trip_completed" and e.user_id == dono)
        assert aviso.payload["pay"]["charge_id"] == charge.charge_id
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 0


def test_motoqueiro_confirma_dinheiro_recebido_pelo_servico_de_corridas(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    make_online_rider(session, positions, 2, pt(900, 0), now=AGORA)
    with pytest.raises(NotYourRide):
        w.trips.confirm_cash_received(session, "r2", "ride-1", AGORA + 600)
    w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100


def test_cancelar_em_procura_retira_a_oferta_e_solta_a_moto(w, session, positions, events, reservas):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 3) == CancelResult(0, False)
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert session.query(RideOfferRow).one().status == "expired"
    assert reservas.reserve("r1", "ride-qualquer") is True
    assert "offer_expired" in tipos(events, "r1")


def test_cancelar_depois_do_prazo_gratis_registra_a_compensacao(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)           # aceita em AGORA + 4
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 4 + 61)
    assert resultado == CancelResult(200, False)
    tipo, dados = repo.ride_events(session, "ride-1")[-1]
    assert tipo == "cancelled" and dados["compensation_cents"] == 200 and dados["by"] == "passenger"


def test_cancelar_dentro_do_prazo_gratis_nao_tem_compensacao(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    assert w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 4 + 30) == CancelResult(0, False)


def test_cancelar_corrida_paga_devolve_o_pix_e_libera_o_motoqueiro(w, session, positions, provider, events):
    add_passenger(session)
    aceitar(session, positions, w)
    pagar(session, w)
    resultado = w.trips.cancel_by_passenger(session, "p1", "ride-1", AGORA + 10)
    assert resultado.refund_needed is True
    assert PgLedger(session).balance("rider:r1") == 0
    assert queries.rider_active_ride_id(session, "r1") is None
    assert "ride_cancelled" in tipos(events, "r1")


def _com_corrida_na_fila(session, positions, w, pagar_a_da_fila=False):
    """r1 está terminando a corrida ride-0 (dinheiro) e aceitou ride-1 (Pix) para a fila."""
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0",
            destination=pt(300, 0))
    w.trips.arrive(session, "r1", "ride-0", AGORA + 50)
    w.trips.confirm_helmet(session, "r1", "ride-0", AGORA + 51)
    w.trips.start_trip(session, "r1", "ride-0", "4821", AGORA + 52)
    positions.update("r1", pt(150, 0), now=AGORA + 100)     # a 150 m do destino: "terminando"
    add_searching_ride(session, "ride-1", "p1", now=AGORA + 100)
    assert w.dispatch.offer_next(session, "ride-1", AGORA + 100) == "r1"
    ride = w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101)
    assert ride.state is RideState.QUEUED
    if pagar_a_da_fila:
        pagar(session, w, "ride-1")


def test_ao_terminar_o_motoqueiro_assume_a_corrida_da_fila(w, session, positions, events):
    _com_corrida_na_fila(session, positions, w)
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.ACCEPTED and ride.en_route_since == AGORA + 400
    assert "rider_on_the_way" in tipos(events, "p1") and "next_ride" in tipos(events, "r1")
    assert "promoted" in [k for k, _ in repo.ride_events(session, "ride-1")]


def test_10a_corrida_sem_entrada_devolve_a_da_fila_para_a_busca_e_reoferece(w, session, positions, events, provider):
    # Review Focus 3 (rede de segurança: a contagem chegou a 10 depois de a fila ter sido aceita)
    _com_corrida_na_fila(session, positions, w, pagar_a_da_fila=True)
    make_online_rider(session, positions, 2, pt(120, 0), now=AGORA + 380)
    acc = repo.get_rider_account(session, "r1")
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    w.trips.complete_trip(session, "r1", "ride-0", AGORA + 400)
    ride = repo.get_ride(session, "ride-1")
    assert ride.state is RideState.SEARCHING and ride.rider_id is None
    assert repo.get_current_charge_id(session, "ride-1") is None
    assert PgLedger(session).balance("rider:r1") == 0           # o Pix da fila foi devolvido
    assert queries.get_pending_offer(session, "ride-1").rider_id == "r2"
    assert "queue_released" in tipos(events, "p1")
    with pytest.raises(CannotGoOnline) as erro:
        RiderService(positions, events).go_online(session, "r1", dt.date(2027, 1, 15))
    assert erro.value.code == "entry_pending"


def test_depois_de_terminar_o_motoqueiro_ocupado_nao_pega_a_fila_ainda(w, session, positions):
    _com_corrida_na_fila(session, positions, w)
    w.trips.after_ride_ends(session, "r1", AGORA + 200)   # ride-0 ainda está em andamento
    assert repo.get_ride(session, "ride-1").state is RideState.QUEUED


def test_avaliacao_atualiza_a_nota_do_motoqueiro(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    ate_o_fim(session, w)
    w.trips.rate(session, "p1", "ride-1", 5, AGORA + 600)
    ficha = queries.rider_card(session, "r1")
    assert (ficha.rating, ficha.rating_count) == (5.0, 1)
    w.trips.rate(session, "r1", "ride-1", 3, AGORA + 601)         # o motoqueiro avalia o passageiro
    assert queries.rider_card(session, "r1").rating_count == 1


def test_avaliacao_recusa_repetida_antes_do_fim_fora_da_faixa_e_de_estranho(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="depois que a corrida acaba"):
        w.trips.rate(session, "p1", "ride-1", 5, AGORA + 10)
    ate_o_fim(session, w)
    for ruim in (0, 6):
        with pytest.raises(ValueError, match="1 a 5"):
            w.trips.rate(session, "p1", "ride-1", ruim, AGORA + 600)
    with pytest.raises(NotYourRide):
        w.trips.rate(session, "p-estranho", "ride-1", 5, AGORA + 600)
    w.trips.rate(session, "p1", "ride-1", 4, AGORA + 600)
    with pytest.raises(AlreadyRated):
        w.trips.rate(session, "p1", "ride-1", 5, AGORA + 601)
    assert queries.rider_card(session, "r1").rating_count == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_trips.py -q 2>&1 | tail -6`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.services.trips'`.

- [ ] **Step 3: Implementar**

Em `server/app/db/queries.py`, acrescentar no fim:

```python


def queued_ride_id_of_rider(session: Session, rider_id: str) -> str | None:
    return session.execute(
        select(RideRow.id).where(RideRow.rider_id == rider_id, RideRow.state == RideState.QUEUED.value).limit(1)
    ).scalar_one_or_none()
```

Em `server/app/services/dispatch.py`, acrescentar à classe `DispatchService`, depois de `decline_offer`:

```python

    def withdraw_offer(self, session: Session, ride_id: str) -> None:
        """A corrida saiu da procura (por exemplo, o passageiro cancelou): tira a oferta e solta a moto."""
        pending = queries.get_pending_offer(session, ride_id, for_update=True)
        if pending is None:
            return
        pending.status = "expired"
        session.flush()
        self.reservations.release(pending.rider_id, ride_id)
        self.events.add(pending.rider_id, "offer_expired", {"ride_id": ride_id})
```

`server/app/services/trips.py`:

```python
"""Andamento da corrida: chegada, capacete, código, fim, cancelamento, fila e avaliação (spec, seção 5)."""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RatingRow, RiderProfileRow
from app.domain.fees import count_completed_ride, offer_block_reason
from app.domain.rides import (
    CancelResult,
    InvalidTransition,
    Ride,
    RideState,
    complete,
    confirm_helmet,
    mark_arrived,
    promote_from_queue,
    start_ride,
)
from app.domain.types import PaymentMethod
from app.services.events import EventCollector
from app.services.payments import PaymentService


class NotYourRide(Exception):
    """A corrida é de outra pessoa."""


class AlreadyRated(Exception):
    """Esta pessoa já avaliou esta corrida."""


class Dispatcher(Protocol):
    def offer_next(self, session: Session, ride_id: str, now: float) -> str | None: ...

    def withdraw_offer(self, session: Session, ride_id: str) -> None: ...


class TripService:
    def __init__(
        self, payments: PaymentService, dispatcher: Dispatcher, events: EventCollector, cfg: AppConfig | None = None
    ) -> None:
        self.payments = payments
        self.dispatcher = dispatcher
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def _rider_ride(self, session: Session, rider_id: str, ride_id: str) -> Ride:
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.rider_id != rider_id:
            raise NotYourRide("Essa corrida não é sua.")
        return ride

    # --- etapas feitas pelo motoqueiro -------------------------------------------------------

    def arrive(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        mark_arrived(ride, now)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "arrived", {}, now)
        self.events.add(ride.passenger_id, "rider_arrived", {"ride_id": ride_id})

    def confirm_helmet(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        confirm_helmet(ride)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "helmet_confirmed", {}, now)

    def start_trip(self, session: Session, rider_id: str, ride_id: str, pin: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        start_ride(ride, pin)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "started", {}, now)
        self.events.add(ride.passenger_id, "trip_started", {"ride_id": ride_id})

    def complete_trip(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        ride = self._rider_ride(session, rider_id, ride_id)
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        complete(ride, now)
        count_completed_ride(acc)
        repo.save_ride(session, ride)
        repo.save_rider_account(session, acc)
        repo.log_ride_event(session, ride_id, "completed", {}, now)
        pay = None
        if ride.payment_method is PaymentMethod.CASH:
            charge = self.payments.start_end_charge(session, ride_id, ride.fee_cents or 0)
            pay = {"charge_id": charge.charge_id, "amount_cents": charge.amount_cents}
        payload = {
            "ride_id": ride_id, "price_cents": ride.price_cents, "method": ride.payment_method.value, "pay": pay,
        }
        self.events.add(ride.passenger_id, "trip_completed", payload)
        self.events.add(rider_id, "trip_completed", payload)
        self.after_ride_ends(session, rider_id, now)

    def confirm_cash_received(self, session: Session, rider_id: str, ride_id: str, now: float) -> None:
        self._rider_ride(session, rider_id, ride_id)
        self.payments.confirm_cash_received(session, ride_id, now)
        repo.log_ride_event(session, ride_id, "cash_confirmed", {}, now)

    # --- fila -----------------------------------------------------------------------------------

    def after_ride_ends(self, session: Session, rider_id: str, now: float) -> None:
        """O motoqueiro ficou livre: assume a corrida da fila, ou a devolve se ele não pode continuar."""
        if queries.rider_active_ride_id(session, rider_id) is not None:
            return
        queued_id = queries.queued_ride_id_of_rider(session, rider_id)
        if queued_id is None:
            return
        acc = repo.get_rider_account(session, rider_id, for_update=True)
        queued = repo.get_ride(session, queued_id, for_update=True)
        if offer_block_reason(acc, self.cfg.fees) is not None:
            refunded = self.payments.release_queued_ride(session, queued_id, now)
            repo.log_ride_event(
                session, queued_id, "queue_released", {"reason": "entrada pendente", "refunded": refunded}, now
            )
            self.events.add(queued.passenger_id, "queue_released", {"ride_id": queued_id, "refunded": refunded})
            self.dispatcher.offer_next(session, queued_id, now)
            return
        promote_from_queue(queued, now)
        repo.save_ride(session, queued)
        repo.log_ride_event(session, queued_id, "promoted", {}, now)
        self.events.add(queued.passenger_id, "rider_on_the_way", {"ride_id": queued_id})
        self.events.add(rider_id, "next_ride", {"ride_id": queued_id})

    # --- cancelamento ---------------------------------------------------------------------------

    def cancel_by_passenger(self, session: Session, passenger_id: str, ride_id: str, now: float) -> CancelResult:
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        state_before, rider_id = ride.state, ride.rider_id
        result = self.payments.cancel_ride(session, ride_id, now)
        repo.log_ride_event(
            session, ride_id, "cancelled",
            {"by": "passenger", "compensation_cents": result.compensation_cents, "refund": result.refund_needed},
            now,
        )
        if state_before in (RideState.REQUESTED, RideState.SEARCHING):
            self.dispatcher.withdraw_offer(session, ride_id)
        if rider_id is not None:
            self.events.add(rider_id, "ride_cancelled", {"ride_id": ride_id, "by": "passenger"})
            if state_before in (RideState.ACCEPTED, RideState.ARRIVED):
                self.after_ride_ends(session, rider_id, now)
        return result

    # --- avaliação ------------------------------------------------------------------------------

    def rate(self, session: Session, user_id: str, ride_id: str, stars: int, now: float) -> None:
        if not 1 <= stars <= 5:
            raise ValueError("A nota vai de 1 a 5.")
        ride = repo.get_ride(session, ride_id)
        if ride.state is not RideState.COMPLETED:
            raise InvalidTransition("Só dá para avaliar depois que a corrida acaba.")
        if user_id == ride.passenger_id:
            to_user = ride.rider_id
        elif user_id == ride.rider_id:
            to_user = ride.passenger_id
        else:
            raise NotYourRide("Essa corrida não é sua.")
        try:
            with session.begin_nested():
                session.add(
                    RatingRow(ride_id=ride_id, from_user=user_id, to_user=to_user, stars=stars, created_at=now)
                )
                session.flush()
        except IntegrityError as exc:
            raise AlreadyRated("Você já avaliou esta corrida.") from exc
        if user_id == ride.passenger_id:
            profile = session.get(RiderProfileRow, to_user, with_for_update=True)
            profile.rating_sum += stars
            profile.rating_count += 1
            session.flush()
        repo.log_ride_event(session, ride_id, "rated", {"by": user_id, "stars": stars}, now)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_trips.py -v 2>&1 | tail -30`
Expected: todos passam (14 testes).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add app tests && git commit -m "feat(services): andamento da corrida, cancelamento, promoção da fila e avaliações" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Varreduras de tempo, cenário do dia e documentação

**Files:**
- Create: `server/app/services/sweeps.py`
- Modify: `server/app/services/dispatch.py` (acrescentar `give_up_if_expired`), `server/app/db/queries.py`, `server/README.md`, `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`
- Test: `server/tests/services/test_sweeps.py`, `server/tests/services/test_dia_de_corridas.py`

**Interfaces:**
- Consumes: todos os serviços das tarefas 3 a 8.
- Produces:
  - Em `queries`: `pix_window_due_ride_ids(session, now, window_s)`, `searching_ride_ids(session)`, `queued_ride_ids_due(session, now, max_wait_s)`, `arrived_ride_ids_due(session, now, max_wait_s)`, `cash_unpaid_ride_ids_due(session, now, wait_s)` (todas devolvem `list[str]` de ids de corrida).
  - Em `DispatchService`: `give_up_if_expired(session, ride_id, now) -> bool` (procura passou de `search_give_up_s` sem oferta pendente: corrida vira `NO_RIDER` e o passageiro é avisado).
  - `SweepReport(offers_expired, pix_expired, queue_released, arrival_cancelled, cash_blocked, searches_given_up, errors)` e `SweepService(payments, dispatcher, trips, events, cfg=None).run(session, now) -> SweepReport`. Cada corrida é tratada num ponto de salvamento: um erro numa corrida vai para `errors` e não trava as outras.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/services/test_sweeps.py`:

```python
from types import SimpleNamespace

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.models import RideOfferRow, UserRow
from app.db.pg_ledger import PgLedger
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryPositionStore
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.sweeps import SweepReport, SweepService
from app.services.trips import TripService
from tests.helpers import pt
from tests.helpers_db import add_passenger, add_searching_ride, make_online_rider

AGORA = 1_800_000_000.0


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def provider():
    return FakePaymentProvider()


@pytest.fixture()
def w(positions, provider, events):
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), FakeMaps(), payments, events)
    trips = TripService(payments, dispatch, events)
    sweeps = SweepService(payments, dispatch, trips, events)
    return SimpleNamespace(payments=payments, dispatch=dispatch, trips=trips, sweeps=sweeps, provider=provider)


def aceitar(session, positions, w, method=PaymentMethod.PIX, ride_id="ride-1", passenger_id="p1", rider_n=1, now=AGORA):
    if session.get(UserRow, passenger_id) is None:
        add_passenger(session, passenger_id, f"+5575900002{int(passenger_id[1:]):03d}")
    make_online_rider(session, positions, rider_n, pt(100 * rider_n, 0), now=now)
    add_searching_ride(session, ride_id, passenger_id, method=method, now=now)
    w.dispatch.offer_next(session, ride_id, now)
    return w.dispatch.accept_offer(session, f"r{rider_n}", ride_id, now + 1)


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_sem_nada_vencido_nada_acontece(w, session):
    relatorio = w.sweeps.run(session, AGORA)
    assert relatorio == SweepReport()      # tudo zerado e sem erros


def test_oferta_vencida_passa_para_a_proxima_moto(w, session, positions):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA)
    make_online_rider(session, positions, 2, pt(200, 0), now=AGORA)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA)
    assert w.sweeps.run(session, AGORA + 16).offers_expired == 1
    assert {o.rider_id: o.status for o in session.query(RideOfferRow)} == {"r1": "expired", "r2": "pending"}


def test_pix_nao_pago_em_2_minutos_cancela_e_libera_o_motoqueiro(w, session, positions, events):
    add_passenger(session)
    aceitar(session, positions, w)                       # Pix criado em AGORA + 1
    assert w.sweeps.run(session, AGORA + 120).pix_expired == 0
    relatorio = w.sweeps.run(session, AGORA + 1 + 120)
    assert relatorio.pix_expired == 1 and relatorio.errors == []
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert queries.rider_active_ride_id(session, "r1") is None
    assert "ride_cancelled" in tipos(events, "p1") and "ride_cancelled" in tipos(events, "r1")


def test_procura_desiste_depois_de_2_minutos_e_avisa_o_passageiro(w, session, events):
    add_passenger(session)
    add_searching_ride(session, now=AGORA)
    assert w.sweeps.run(session, AGORA + 119).searches_given_up == 0
    assert w.sweeps.run(session, AGORA + 121).searches_given_up == 1
    assert repo.get_ride(session, "ride-1").state is RideState.NO_RIDER
    assert "no_rider" in tipos(events, "p1")


def test_nao_desiste_enquanto_ha_oferta_pendente(w, session, positions):
    add_passenger(session)
    make_online_rider(session, positions, 1, pt(100, 0), now=AGORA + 110)
    add_searching_ride(session, now=AGORA)
    w.dispatch.offer_next(session, "ride-1", AGORA + 110)
    assert w.sweeps.run(session, AGORA + 121).searches_given_up == 0
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING


def test_fila_que_passa_de_8_minutos_volta_para_a_busca_com_outra_moto(w, session, positions):
    add_passenger(session, "p0", "+5575900000010")
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH, ride_id="ride-0", passenger_id="p0")
    ride0 = repo.get_ride(session, "ride-0")
    ride0.state = RideState.IN_PROGRESS
    repo.save_ride(session, ride0)
    repo.set_ride_details(session, "ride-0", repo.RideDetails(pt(0, 0), pt(300, 0), "A", "B", 400, 1.0, ""))
    positions.update("r1", pt(150, 0), now=AGORA + 100)
    # corrida da fila em dinheiro: uma da fila em Pix venceria antes (o passageiro tem 2 minutos para pagar)
    add_searching_ride(session, "ride-1", "p1", method=PaymentMethod.CASH, now=AGORA + 100)
    w.dispatch.offer_next(session, "ride-1", AGORA + 100)
    w.dispatch.accept_offer(session, "r1", "ride-1", AGORA + 101)
    assert repo.get_ride(session, "ride-1").state is RideState.QUEUED
    make_online_rider(session, positions, 2, pt(120, 0), now=AGORA + 101 + 480)
    positions.update("r1", pt(150, 0), now=AGORA + 101 + 480)
    relatorio = w.sweeps.run(session, AGORA + 101 + 480)
    assert relatorio.queue_released == 1
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
    assert queries.get_pending_offer(session, "ride-1").rider_id == "r2"


def test_espera_na_chegada_de_5_minutos_cancela_com_devolucao_do_pix(w, session, positions, provider, events):
    add_passenger(session)
    aceitar(session, positions, w)
    charge_id = repo.get_current_charge_id(session, "ride-1")
    w.payments.on_provider_event(session, provider.mark_paid(charge_id))
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    assert w.sweeps.run(session, AGORA + 50 + 299).arrival_cancelled == 0
    relatorio = w.sweeps.run(session, AGORA + 50 + 300)
    assert relatorio.arrival_cancelled == 1
    assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
    assert provider.charges[charge_id].refunded is True
    assert PgLedger(session).balance("rider:r1") == 0
    tipo, dados = repo.ride_events(session, "ride-1")[-1]
    assert tipo == "cancelled" and dados["by"] == "timeout" and dados["compensation_cents"] == 200


def test_pagamento_em_dinheiro_nao_confirmado_bloqueia_o_passageiro(w, session, positions):
    add_passenger(session)
    aceitar(session, positions, w, method=PaymentMethod.CASH)
    w.trips.arrive(session, "r1", "ride-1", AGORA + 50)
    w.trips.confirm_helmet(session, "r1", "ride-1", AGORA + 51)
    w.trips.start_trip(session, "r1", "ride-1", "4821", AGORA + 52)
    w.trips.complete_trip(session, "r1", "ride-1", AGORA + 400)
    assert w.sweeps.run(session, AGORA + 699).cash_blocked == 0
    assert w.sweeps.run(session, AGORA + 700).cash_blocked == 1
    assert repo.get_passenger_account(session, "p1").unpaid_cents == 700
    assert w.sweeps.run(session, AGORA + 800).cash_blocked == 0


def test_erro_em_uma_corrida_nao_trava_as_outras(session, positions, provider, events):
    class DespachanteQuebrado(DispatchService):
        def offer_next(self, session, ride_id, now):
            if ride_id == "ride-1":
                raise RuntimeError("falha de teste")
            return super().offer_next(session, ride_id, now)

    payments = PaymentService(provider, events=events)
    dispatch = DespachanteQuebrado(positions, ReservationBook(), FakeMaps(), payments, events)
    sweeps = SweepService(payments, dispatch, TripService(payments, dispatch, events), events)
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000012")
    add_searching_ride(session, "ride-1", "p1", now=AGORA)
    add_searching_ride(session, "ride-2", "p2", now=AGORA)
    relatorio = sweeps.run(session, AGORA + 121)
    assert len(relatorio.errors) == 1 and "ride-1" in relatorio.errors[0]
    assert repo.get_ride(session, "ride-2").state is RideState.NO_RIDER
    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
```

`server/tests/services/test_dia_de_corridas.py`:

```python
import datetime as dt

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_otp import FakeOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.db import queries
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.clock import local_date
from app.domain.dispatch import ReservationBook
from app.domain.rides import RideState
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.auth import AuthService, normalize_phone
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from app.services.riders import CannotGoOnline, RiderService
from app.services.sweeps import SweepService
from app.services.trips import TripService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import make_cpf

AGORA = 1_800_000_000.0


def test_um_dia_de_ponta_a_ponta_com_pix_dinheiro_bloqueio_e_entrada(session):
    provider, events, sender = FakePaymentProvider(), EventCollector(), FakeOtpSender()
    positions, maps = InMemoryPositionStore(), FakeMaps()
    auth, riders = AuthService(sender), RiderService(positions, events)
    payments = PaymentService(provider, events=events)
    dispatch = DispatchService(positions, ReservationBook(), maps, payments, events)
    trips = TripService(payments, dispatch, events)
    quotes = QuoteService(maps, positions, InMemoryFactorStore())
    requests = RideRequestService(dispatch, events)
    sweeps = SweepService(payments, dispatch, trips, events)
    hoje = local_date(AGORA)

    def entrar(phone: str, role: str, t: float):
        auth.request_code(session, phone, t)
        return auth.verify_code(session, phone, sender.last_code(normalize_phone(phone)), role, "celular", t + 1)

    def pedir(passageiro, metodo: PaymentMethod, t: float):
        riders.report_position(rider.user_id, pt(300, 0), t - 1)
        quote = quotes.create_quote(session, passageiro.user_id, ORIGIN, pt(1500, 0), "Rua A", "Feira livre", t)
        ride = requests.request_ride(session, passageiro.user_id, quote.quote_id, metodo, t + 1)
        return dispatch.accept_offer(session, rider.user_id, ride.ride_id, t + 3)

    def percurso(ride, t: float):
        trips.arrive(session, rider.user_id, ride.ride_id, t)
        trips.confirm_helmet(session, rider.user_id, ride.ride_id, t + 1)
        trips.start_trip(session, rider.user_id, ride.ride_id, ride.pin, t + 5)
        trips.complete_trip(session, rider.user_id, ride.ride_id, t + 300)

    # 1) login do passageiro e do motoqueiro; cadastro e aprovação; motoqueiro fica disponível
    pax = entrar("75 99999-0001", "passenger", AGORA)
    rider = entrar("75 99999-0002", "rider", AGORA)
    assert pax.ok and rider.ok
    riders.register_rider(
        session, rider.user_id, name="Carlos Moto", cpf=make_cpf("123456789"), cnh_number="12345678901",
        plate="ABC1D23", moto_model="Honda CG 160", selfie_key="s", cnh_photo_key="c", crlv_key="m",
        cnh_expires_on=hoje + dt.timedelta(days=700), crlv_expires_on=hoje + dt.timedelta(days=300), today=hoje,
    )
    riders.approve(session, rider.user_id, AGORA + 5)
    riders.go_online(session, rider.user_id, hoje)

    # 2) corrida 1, Pix: pedido -> oferta -> aceite -> pago -> andamento -> avaliação
    ride1 = pedir(pax, PaymentMethod.PIX, AGORA + 10)
    assert ride1.state is RideState.ACCEPTED and ride1.fee_cents == 100
    charge1 = repo.get_current_charge_id(session, ride1.ride_id)
    assert payments.on_provider_event(session, provider.mark_paid(charge1)) == "applied"
    percurso(ride1, AGORA + 100)
    trips.rate(session, pax.user_id, ride1.ride_id, 5, AGORA + 500)
    assert queries.rider_card(session, rider.user_id).rating == 5.0
    preco1 = repo.get_ride(session, ride1.ride_id).price_cents

    # 3) corrida 2, dinheiro: passageiro não paga; passa o prazo; é bloqueado; paga atrasado pelo QR
    ride2 = pedir(pax, PaymentMethod.CASH, AGORA + 1000)
    percurso(ride2, AGORA + 1100)
    qr2 = repo.get_current_charge_id(session, ride2.ride_id)
    fim2 = AGORA + 1100 + 300
    assert sweeps.run(session, fim2 + 301).cash_blocked == 1
    assert repo.get_passenger_account(session, pax.user_id).unpaid_cents > 0
    with pytest.raises(NotAllowed, match="Falta pagar"):
        quotes.create_quote(session, pax.user_id, ORIGIN, pt(1500, 0), "A", "B", fim2 + 400)
    assert repo.get_rider_account(session, rider.user_id).cash_debt_cents == 0   # sem taxa no calote
    assert payments.on_provider_event(session, provider.mark_paid(qr2)) == "applied"
    assert repo.get_passenger_account(session, pax.user_id).unpaid_cents == 0
    preco2 = repo.get_ride(session, ride2.ride_id).price_cents

    # 4) corrida 3, dinheiro pago na mão: o motoqueiro confirma e a taxa vira dívida dele
    ride3 = pedir(pax, PaymentMethod.CASH, AGORA + 3000)
    percurso(ride3, AGORA + 3100)
    trips.confirm_cash_received(session, rider.user_id, ride3.ride_id, AGORA + 3500)
    assert repo.get_rider_account(session, rider.user_id).cash_debt_cents == 100
    assert repo.get_rider_account(session, rider.user_id).completed_rides == 3

    # 5) 10 corridas feitas: sem entrada não fica disponível; paga a entrada e volta
    acc = repo.get_rider_account(session, rider.user_id)
    acc.completed_rides = 10
    repo.save_rider_account(session, acc)
    with pytest.raises(CannotGoOnline) as erro:
        riders.go_online(session, rider.user_id, hoje)
    assert erro.value.code == "entry_pending"
    entrada = payments.start_entry_charge(session, rider.user_id)
    assert payments.on_provider_event(session, provider.mark_paid(entrada.charge_id)) == "applied"
    riders.go_online(session, rider.user_id, hoje)

    # 6) fechamento do dia: o livro soma zero e bate com o extrato do provedor
    ledger = PgLedger(session)
    assert ledger.is_balanced() is True
    assert ledger.balance(f"rider:{rider.user_id}") == (preco1 - 100) + (preco2 - 100)
    assert ledger.balance(PgLedger.COMPANY) == 100 + 100 + 5000
    assert ledger.balance(PgLedger.PROVIDER) == -(preco1 + preco2 + 5000)
    extrato = {
        (f"entry:{c.rider_id}" if c.purpose == "entry" else f"charge:{c.charge_id}"): c.amount_cents
        for c in provider.charges.values()
        if c.paid and not c.refunded
    }
    assert ledger.reconcile(extrato) == {}
    tipos = {e.type for e in events.events}
    assert {"offer", "rider_accepted", "trip_completed", "passenger_blocked", "unblocked", "entry_paid"} <= tipos
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/services/test_sweeps.py tests/services/test_dia_de_corridas.py -q 2>&1 | tail -6`
Expected: erro de coleta `ModuleNotFoundError: No module named 'app.services.sweeps'`.

- [ ] **Step 3: Implementar**

Em `server/app/db/queries.py`, acrescentar no fim:

```python


def pix_window_due_ride_ids(session: Session, now: float, window_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(
                RideRow.payment_method == "pix",
                RideRow.pix_paid.is_(False),
                RideRow.state.in_((RideState.QUEUED.value, RideState.ACCEPTED.value, RideState.ARRIVED.value)),
                RideRow.pix_charge_created_at <= now - window_s,
            )
            .order_by(RideRow.id)
        ).scalars()
    )


def searching_ride_ids(session: Session) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id).where(RideRow.state == RideState.SEARCHING.value).order_by(RideRow.searching_since)
        ).scalars()
    )


def queued_ride_ids_due(session: Session, now: float, max_wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(RideRow.state == RideState.QUEUED.value, RideRow.queued_since <= now - max_wait_s)
            .order_by(RideRow.id)
        ).scalars()
    )


def arrived_ride_ids_due(session: Session, now: float, max_wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(RideRow.state == RideState.ARRIVED.value, RideRow.arrived_at <= now - max_wait_s)
            .order_by(RideRow.id)
        ).scalars()
    )


def cash_unpaid_ride_ids_due(session: Session, now: float, wait_s: float) -> list[str]:
    return list(
        session.execute(
            select(RideRow.id)
            .where(
                RideRow.state == RideState.COMPLETED.value,
                RideRow.payment_method == "cash",
                RideRow.end_payment_confirmed.is_(False),
                RideRow.non_payment_reported.is_(False),
                RideRow.completed_at <= now - wait_s,
            )
            .order_by(RideRow.id)
        ).scalars()
    )
```

Em `server/app/services/dispatch.py`: acrescentar `mark_no_rider` à importação de `app.domain.rides` e, na classe `DispatchService`, depois de `withdraw_offer`:

```python

    def give_up_if_expired(self, session: Session, ride_id: str, now: float) -> bool:
        """Passaram `search_give_up_s` sem moto e sem oferta pendente: a corrida fica sem motoqueiro."""
        ride = repo.get_ride(session, ride_id, for_update=True)
        if ride.state is not RideState.SEARCHING or queries.get_pending_offer(session, ride_id) is not None:
            return False
        if ride.searching_since is None or now - ride.searching_since < self.cfg.rides.search_give_up_s:
            return False
        mark_no_rider(ride, now, self.cfg.rides)
        repo.save_ride(session, ride)
        repo.log_ride_event(session, ride_id, "no_rider", {}, now)
        self.events.add(ride.passenger_id, "no_rider", {"ride_id": ride_id})
        return True
```

`server/app/services/sweeps.py`:

```python
"""Tarefas de tempo, rodadas de poucos em poucos segundos pelo servidor (spec, seções 5 e 12).

Cada corrida é tratada num ponto de salvamento: se uma falhar, o erro vai para o relatório e as
outras seguem. Quem chama faz o commit (ou o rollback) do conjunto.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.domain.rides import arrival_wait_expired, queue_wait_expired
from app.services.dispatch import DispatchService
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.trips import TripService


@dataclass
class SweepReport:
    offers_expired: int = 0
    pix_expired: int = 0
    queue_released: int = 0
    arrival_cancelled: int = 0
    cash_blocked: int = 0
    searches_given_up: int = 0
    errors: list[str] = field(default_factory=list)


class SweepService:
    def __init__(
        self,
        payments: PaymentService,
        dispatcher: DispatchService,
        trips: TripService,
        events: EventCollector,
        cfg: AppConfig | None = None,
    ) -> None:
        self.payments = payments
        self.dispatcher = dispatcher
        self.trips = trips
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    def _each(
        self, session: Session, report: SweepReport, label: str, ride_ids: list[str], action: Callable[[str], bool]
    ) -> int:
        done = 0
        for ride_id in ride_ids:
            try:
                with session.begin_nested():
                    if action(ride_id):
                        done += 1
            except Exception as exc:  # um pedido com problema não pode travar os outros
                report.errors.append(f"{label} {ride_id}: {exc}")
        return done

    def run(self, session: Session, now: float) -> SweepReport:
        report = SweepReport()
        rides = self.cfg.rides

        def offers(ride_id: str) -> bool:
            self.dispatcher.offer_next(session, ride_id, now)
            return True

        def pix(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id)
            if not self.payments.expire_unpaid_pix(session, ride_id, now):
                return False
            repo.log_ride_event(session, ride_id, "cancelled", {"by": "timeout", "reason": "pix_expired"}, now)
            self.events.add(ride.passenger_id, "ride_cancelled", {"ride_id": ride_id, "reason": "pix_expired"})
            if ride.rider_id is not None:
                self.events.add(ride.rider_id, "ride_cancelled", {"ride_id": ride_id, "reason": "pix_expired"})
                self.trips.after_ride_ends(session, ride.rider_id, now)
            return True

        def queue(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id)
            if not queue_wait_expired(ride, now, rides):
                return False
            refunded = self.payments.release_queued_ride(session, ride_id, now)
            repo.log_ride_event(
                session, ride_id, "queue_released", {"reason": "queue_timeout", "refunded": refunded}, now
            )
            self.events.add(ride.passenger_id, "queue_released", {"ride_id": ride_id, "refunded": refunded})
            self.dispatcher.offer_next(session, ride_id, now)
            return True

        def arrival(ride_id: str) -> bool:
            ride = repo.get_ride(session, ride_id)
            if not arrival_wait_expired(ride, now, rides):
                return False
            result = self.payments.cancel_after_arrival_timeout(session, ride_id, now)
            repo.log_ride_event(
                session, ride_id, "cancelled",
                {"by": "timeout", "reason": "arrival_wait",
                 "compensation_cents": result.compensation_cents, "refund": result.refund_needed},
                now,
            )
            self.events.add(ride.passenger_id, "ride_cancelled", {"ride_id": ride_id, "reason": "arrival_wait"})
            if ride.rider_id is not None:
                self.events.add(ride.rider_id, "ride_cancelled", {"ride_id": ride_id, "reason": "arrival_wait"})
                self.trips.after_ride_ends(session, ride.rider_id, now)
            return True

        def cash(ride_id: str) -> bool:
            return self.payments.block_unpaid_cash_ride(session, ride_id, now)

        def searching(ride_id: str) -> bool:
            if self.dispatcher.offer_next(session, ride_id, now) is not None:
                return False
            return self.dispatcher.give_up_if_expired(session, ride_id, now)

        report.offers_expired = self._each(session, report, "oferta", queries.due_offer_ride_ids(session, now), offers)
        report.pix_expired = self._each(
            session, report, "pix", queries.pix_window_due_ride_ids(session, now, rides.pix_window_s), pix
        )
        report.queue_released = self._each(
            session, report, "fila", queries.queued_ride_ids_due(session, now, rides.queue_max_wait_s), queue
        )
        report.arrival_cancelled = self._each(
            session, report, "chegada", queries.arrived_ride_ids_due(session, now, rides.max_wait_at_arrival_s), arrival
        )
        report.cash_blocked = self._each(
            session, report, "dinheiro", queries.cash_unpaid_ride_ids_due(session, now, rides.cash_pay_wait_s), cash
        )
        report.searches_given_up = self._each(
            session, report, "procura", queries.searching_ride_ids(session), searching
        )
        return report
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/services/test_sweeps.py tests/services/test_dia_de_corridas.py -v 2>&1 | tail -20`
Expected: todos passam (9 de varreduras e 1 do dia).

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam.

- [ ] **Step 5: Atualizar a documentação**

Em `server/README.md`: na seção `## Mapa do código`, acrescentar as linhas:

```markdown
- `app/services/auth.py` — login por código (WhatsApp falso nos testes) e sessões; `riders.py` — cadastro, aprovação, bloqueio e disponibilidade do motoqueiro; `quotes.py` e `ride_requests.py` — preço antes do pedido e pedido de corrida; `dispatch.py` — procura e ofertas uma por vez, com fila; `trips.py` — andamento, cancelamento, fila e avaliações; `sweeps.py` — tarefas de tempo (ofertas, Pix, fila, chegada, pagamento em dinheiro, procura); `events.py` — avisos para os apps (publicados só depois do commit, no plano 2C).
- `app/db/queries.py` — consultas de leitura usadas pelos serviços.
```

e na seção `## Regras de convivência`, acrescentar:

```markdown
- Os serviços recebem `now` como parâmetro e anotam avisos num `EventCollector`; quem chama publica depois do commit.
- Login: `AuthService.verify_code` não levanta erro para código errado; devolve `ok=False` para a tentativa ser gravada.
- Ordem de travas: corrida, motoqueiro, cobrança, passageiro.
```

Em `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`: trocar a linha da tabela do plano `2B` por:

```markdown
| 2B | **Corrida de ponta a ponta, em serviços** (`2026-10-09-02b-corrida-de-ponta-a-ponta.md`) | Login por código, cadastro e aprovação do motoqueiro, preço e pedido, procura e ofertas (uma por vez, com fila), andamento da corrida, dinheiro do fim da corrida em dinheiro vivo (QR, bloqueio automático e repasse ao motoqueiro quando o passageiro paga), taxa de entrada, avaliações e varreduras de tempo. Sem HTTP. | 2A | não |
| 2C | **API e tempo real** (plano escrito depois do 2B) | FastAPI sobre os serviços do 2B: rotas, autenticação por token, webhook do provedor (conferindo valor e corrida), WebSocket, publicação dos avisos depois do commit, repetição das varreduras e da checagem diária de documentos, aviso de segurança (parada longa e saída da rota) com o SOS, envio de documentos. | 2B | não |
```

e trocar a seção `## Itens obrigatórios para o plano 2B (vindos da revisão final do 2A)` (título e lista) por:

```markdown
## Itens para o plano 2C

Vindos da revisão final do 2A (ainda abertos):
- Aviso do provedor para cobrança desconhecida levanta `LookupError`: a camada HTTP decide se confirma ou falha.
- Conferir `amount_cents` e `ride_id` do aviso com a cobrança gravada e autenticar o webhook.
- `save_rider_account` regrava as quatro colunas: só chamar depois de ler com `for_update=True`.
- Criar o cliente Redis sempre com `decode_responses=True` (as posições recusam cliente sem isso).
- Limpar do Redis (`pos:geo`, `pos:seen`) as motos que somem sem avisar.
- CHECKs em `pix_charges` e chave estrangeira em `rides.current_charge_id` numa migração nova; transformar o `compare_metadata` do Alembic em teste.

Vindos do plano 2B:
- Publicar os avisos do `EventCollector` somente depois do `commit` e rodar `SweepService.run` a cada poucos segundos (um commit por rodada, erros do relatório vão para o registro).
- Rodar `RiderService.block_expired_documents` uma vez por dia.
- Compensação do cancelamento tardio: hoje só fica registrada no histórico da corrida (`cancelled`), sem movimento de dinheiro. Decidir a política (valor em aberto na spec) e como cobrar.
- Pagamento atrasado de corrida em dinheiro: a cobrança do QR do fim continua valendo; com a Woovi real ela expira, então será preciso recriá-la quando o passageiro abrir a tela "Pagamento pendente".
- Dívida reservada de um QR que nunca é pago continua reservada até alguém pagar ou o Levy resolver no painel (ver plano 4).
- O Pix que cria a cobrança e a chamada ao provedor continuam dentro da transação (idempotência no plano 7).
- Aviso de segurança durante a corrida (usar `app.domain.safety.evaluate`), SOS e "tudo bem?" do passageiro.
- Decidir se a corrida com bloqueio por falta de pagamento conta para as 10 corridas de teste (hoje conta).
```

e remover da seção os dois itens antigos do calote (o texto "Corrida em dinheiro sem pagamento…" e "Pendente do Levy…") passando-os para uma frase em `## Decisões já tomadas`: "Corrida em dinheiro sem pagamento: bloqueio automático após 5 minutos, sem taxa para o motoqueiro, repasse quando o passageiro pagar (feito no 2B). Em aberto, com o Levy: se o passageiro nunca pagar, quem arca com o prejuízo (por enquanto, o motoqueiro)."

- [ ] **Step 6: Rodar tudo e conferir**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam. Anotar o total no resumo final.

Run: `.venv/bin/alembic current`
Expected: `0002 (head)`.

Run: `cd .. && git status --short | head`
Expected: apenas os arquivos desta tarefa; `server/.env` não aparece.

- [ ] **Step 7: Commit**

```bash
git add server docs && git commit -m "feat(services): varreduras de tempo, cenário de um dia de ponta a ponta e documentação" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Autoavaliação (feita ao escrever o plano)

**Cobertura da spec:**
- 4 (telas) e 5.1 (etapas): pedido (Tarefa 5), procura e oferta (6), a caminho, chegada, código, capacete, em andamento e fim (8), avaliação (8).
- 5.2 (uma corrida por vez, fila): garantida por oferta única no banco (1), reserva (2A/6), fila com limite de 1 (6), promoção e devolução (8), espera máxima na fila (9).
- 5.3 (cancelamento): grátis até 1 minuto, compensação registrada, espera máxima na chegada (8 e 9). O dinheiro da compensação fica fora (ver abaixo).
- 6 (preço): tarifa, fator por pedidos e motos livres, suavização, motivo, preço travado na cotação (5).
- 7.2 (pagamentos): Pix ao aceitar (6), dinheiro com QR no fim, confirmação, bloqueio automático e repasse (7), entrada de R$ 50 (7).
- 8 (cadastro): documentos, unicidade, aprovação, bloqueio por documento vencido, ficha para o passageiro (4).
- 10.4 (login): código de WhatsApp (falso), limite de pedidos, sessão longa (3). SMS de reserva e o envio real ficam no plano 7.
- 12 (resiliência): aviso repetido (2A/7), Pix vencido (9), dois pedidos para a mesma moto (6), erro isolado por corrida nas varreduras (9).

**Fora deste plano de propósito (plano 2C):** HTTP, WebSocket, publicação dos avisos, webhook, aviso de segurança, agendador, envio de arquivos.
**Fora e em aberto com o Levy:** quem arca com o prejuízo se o passageiro nunca pagar; política e cobrança da compensação de cancelamento; se a corrida bloqueada conta para as 10 de teste.

**Limitações conhecidas:** (1) a chamada ao provedor de pagamento acontece dentro da transação (idempotência no plano 7); (2) a dívida reservada de um QR nunca pago fica reservada; (3) a rede de segurança da 10ª corrida na fila (Tarefa 8) só dispara se a contagem mudar depois do aceite, porque a procura já impede a oferta (Tarefa 6).

**Varredura de lacunas e nomes:** nenhum passo tem "a definir", "tratar erros depois" ou "similar à tarefa N". Os nomes usados nas tarefas seguintes (`EventCollector`, `AuthService`, `RiderService`, `QuoteService`, `RideRequestService`, `DispatchService`, `TripService`, `SweepService`, `PaymentService` com `start_end_charge`, `confirm_cash_received`, `block_unpaid_cash_ride`, `start_entry_charge`, as funções de `queries`, `RideDetails`, `FakeMaps`, `FakeOtpSender`, `InMemoryFactorStore` e os ajudantes de `tests/helpers_db.py`) são os mesmos definidos nas tarefas que os produzem.
