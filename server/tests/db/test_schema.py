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
    with db_engine.connect() as conn:  # só o esquema temporário: `public` tem tabelas do PostGIS
        esquema = conn.execute(text("select current_schema()")).scalar()
    tabelas_no_banco = set(insp.get_table_names(schema=esquema)) - {"alembic_version"}
    assert tabelas_no_banco == set(Base.metadata.tables)
    for nome, tabela in Base.metadata.tables.items():
        colunas_no_banco = {c["name"] for c in insp.get_columns(nome, schema=esquema)}
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
    session.flush()  # sem relationship(), o SQLAlchemy não ordena inserções por chave estrangeira
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
