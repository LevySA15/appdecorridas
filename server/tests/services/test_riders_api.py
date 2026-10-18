import datetime as dt

import pytest

from app.db.models import RiderProfileRow
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.riders import DuplicateRegistration, RegistrationError, RiderService
from tests.services.test_riders import CPF2, HOJE, aprovado, cadastrar, novo_usuario


@pytest.fixture()
def service():
    return RiderService(InMemoryPositionStore(), EventCollector())


def test_cadastro_ao_mesmo_tempo_com_o_mesmo_cpf_vira_cadastro_repetido(service, session, monkeypatch):
    # Roteiro do 2B (menores): `register_rider` concorrente vazava `IntegrityError`.
    aprovado(service, session)
    novo_usuario(session, "r2", "+5575900000003")
    verdadeiro = RiderService._find_duplicate
    chamadas = []

    def cego_na_primeira(self, session, **dados):
        chamadas.append(1)
        return None if len(chamadas) == 1 else verdadeiro(self, session, **dados)

    monkeypatch.setattr(RiderService, "_find_duplicate", cego_na_primeira)
    with pytest.raises(DuplicateRegistration) as erro:
        cadastrar(service, session, "r2", cnh_number="99999999999", plate="ZZZ9Z99")
    assert erro.value.field == "CPF"
    assert session.get(RiderProfileRow, "r2") is None
    cadastrar(service, session, "r2", cpf=CPF2, cnh_number="99999999999", plate="ZZZ9Z99")   # a sessão segue usável
    assert session.get(RiderProfileRow, "r2") is not None


def test_enviar_o_cadastro_duas_vezes_ao_mesmo_tempo_nao_vaza_erro_do_banco(service, session, monkeypatch):
    novo_usuario(session)
    cadastrar(service, session)
    real_get = session.get
    cegas = []

    def get_cego_uma_vez(entidade, ident, *args, **kwargs):
        if entidade is RiderProfileRow and not cegas:
            cegas.append(1)
            return None
        return real_get(entidade, ident, *args, **kwargs)

    monkeypatch.setattr(session, "get", get_cego_uma_vez)
    monkeypatch.setattr(RiderService, "_find_duplicate", lambda self, session, **dados: None)
    with pytest.raises(RegistrationError, match="já foi enviado"):
        cadastrar(service, session)


def test_renovar_documentos_troca_as_fotos_so_quando_vierem_novas(service, session):
    aprovado(service, session)
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
        cnh_photo_key="nova-cnh.jpg",
    )
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.cnh_photo_key, perfil.crlv_key) == ("nova-cnh.jpg", "m.jpg")
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
        crlv_key="novo-crlv.jpg",
    )
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.cnh_photo_key, perfil.crlv_key) == ("nova-cnh.jpg", "novo-crlv.jpg")
