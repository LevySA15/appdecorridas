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


def bloqueado_por_documento_vencido(service, session, events):
    """Aprovado com o documento da moto vencendo em 2026-12-31 e bloqueado pela varredura de 2027-01-01."""
    aprovado(service, session, "r1", crlv_expires_on=dt.date(2026, 12, 31))
    assert service.block_expired_documents(session, dt.date(2027, 1, 1)) == ["r1"]
    events.drain()


def test_renovar_documentos_libera_quem_foi_bloqueado_por_documento_vencido(service, session, events):
    bloqueado_por_documento_vencido(service, session, events)
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1),
        today=dt.date(2027, 1, 1),
    )
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.status, perfil.rejected_reason, perfil.online) == ("approved", None, False)
    assert [e.type for e in events.events] == ["rider_unblocked"]
    service.go_online(session, "r1", dt.date(2027, 1, 1))
    assert session.get(RiderProfileRow, "r1").online is True


def test_renovar_documentos_nao_libera_o_bloqueio_do_administrador(service, session, events):
    aprovado(service, session, "r1")
    service.block(session, "r1", "documento vencido")     # o mesmo texto da varredura, mas é do administrador
    events.drain()
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
    )
    assert session.get(RiderProfileRow, "r1").status == "blocked"
    assert session.get(UserRow, "r1").is_blocked is True
    assert not events.events


def test_renovar_com_data_vencida_continua_bloqueado(service, session, events):
    bloqueado_por_documento_vencido(service, session, events)
    with pytest.raises(RegistrationError, match="vencid"):
        service.renew_documents(
            session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2026, 12, 31),
            today=dt.date(2027, 1, 1),
        )
    assert session.get(RiderProfileRow, "r1").status == "blocked"
    assert not events.events


def test_renovar_documentos_de_quem_nao_esta_bloqueado_nao_emite_aviso(service, session, events):
    aprovado(service, session)
    events.drain()
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
    )
    assert session.get(RiderProfileRow, "r1").status == "approved"
    assert not events.events


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
