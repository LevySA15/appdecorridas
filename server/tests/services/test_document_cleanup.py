import os

import pytest

from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.infra.documents import LocalDocumentStore
from app.services.document_cleanup import (
    ORPHAN_AFTER_S,
    REJECTED_KEEP_S,
    delete_unreferenced,
    referenced_keys,
    release_rejected_photos,
)
from tests.helpers_db import add_rider

AGORA = 1_800_000_000.0
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
DIA = 86_400.0


def perfil_com_fotos(session, store, user_id="r1", status="rejected", rejected_at=None, **dono):
    add_rider(session, user_id, f"+5575900{abs(hash(user_id)) % 100000:05d}", **dono)
    perfil = session.get(RiderProfileRow, user_id)
    perfil.selfie_key = store.save(user_id, "selfie", JPEG)
    perfil.cnh_photo_key = store.save(user_id, "cnh", JPEG)
    perfil.crlv_key = store.save(user_id, "crlv", JPEG)
    perfil.status, perfil.rejected_at = status, rejected_at
    session.flush()
    return perfil


@pytest.fixture()
def store(tmp_path):
    return LocalDocumentStore(tmp_path)


def test_recusado_ha_mais_de_30_dias_perde_as_fotos(session, store):
    perfil = perfil_com_fotos(session, store, rejected_at=AGORA - 31 * DIA)
    chaves = {perfil.selfie_key, perfil.cnh_photo_key, perfil.crlv_key}
    assert set(release_rejected_photos(session, AGORA)) == chaves
    assert (perfil.selfie_key, perfil.cnh_photo_key, perfil.crlv_key) == (None, None, None)
    assert perfil.status == "rejected"          # o cadastro e o motivo continuam; só as fotos saem


def test_recusado_ha_menos_de_30_dias_mantem_as_fotos(session, store):
    perfil = perfil_com_fotos(session, store, rejected_at=AGORA - 29 * DIA)
    assert release_rejected_photos(session, AGORA) == []
    assert perfil.selfie_key is not None


def test_o_prazo_de_30_dias_vem_da_constante(session, store):
    assert REJECTED_KEEP_S == 30 * DIA
    perfil_com_fotos(session, store, rejected_at=AGORA - REJECTED_KEEP_S)
    assert len(release_rejected_photos(session, AGORA)) == 3


@pytest.mark.parametrize("situacao", ["pending", "approved", "blocked"])
def test_quem_nao_foi_recusado_nunca_perde_as_fotos(session, store, situacao):
    perfil = perfil_com_fotos(session, store, status=situacao, rejected_at=AGORA - 400 * DIA)
    assert release_rejected_photos(session, AGORA) == []
    assert perfil.selfie_key is not None


def test_recusado_sem_hora_da_recusa_nao_perde_as_fotos(session, store):
    perfil_com_fotos(session, store, rejected_at=None)
    assert release_rejected_photos(session, AGORA) == []


def test_recusado_que_ja_perdeu_as_fotos_nao_aparece_de_novo(session, store):
    perfil_com_fotos(session, store, rejected_at=AGORA - 40 * DIA)
    assert len(release_rejected_photos(session, AGORA)) == 3
    assert release_rejected_photos(session, AGORA) == []


def envelhecer(store, chave, segundos):
    caminho = store.root / chave
    os.utime(caminho, (AGORA - segundos, AGORA - segundos))


def test_nao_apaga_o_que_algum_cadastro_usa(session, store):
    perfil = perfil_com_fotos(session, store, status="approved")
    sem_dono = store.save("rider-9", "selfie", JPEG)
    for chave in (perfil.selfie_key, perfil.cnh_photo_key, perfil.crlv_key, sem_dono):
        envelhecer(store, chave, 2 * DIA)
    assert delete_unreferenced(store, referenced_keys(session), AGORA) == 1
    assert store.exists(perfil.selfie_key) and store.exists(perfil.cnh_photo_key) and store.exists(perfil.crlv_key)
    assert not store.exists(sem_dono)


def test_arquivo_sem_dono_com_menos_de_24_horas_fica(session, store):
    recente = store.save("rider-9", "selfie", JPEG)
    envelhecer(store, recente, ORPHAN_AFTER_S - 3600)
    assert delete_unreferenced(store, set(), AGORA) == 0
    assert store.exists(recente)


def test_erro_ao_apagar_um_arquivo_nao_impede_os_outros(store):
    a = store.save("rider-8", "selfie", JPEG)
    b = store.save("rider-9", "selfie", JPEG)
    for chave in (a, b):
        envelhecer(store, chave, 2 * DIA)
    real = store.delete
    falhou = []

    def delete_que_falha_uma_vez(chave):
        if not falhou:
            falhou.append(chave)
            raise OSError("sem permissão")
        real(chave)

    store.delete = delete_que_falha_uma_vez
    assert delete_unreferenced(store, set(), AGORA) == 1
    assert sorted(item.key for item in store.list_all()) == [falhou[0]]


def test_chaves_de_quem_tem_foto_em_so_um_campo(session, store):
    add_rider(session)
    session.get(RiderProfileRow, "r1").selfie_key = "r1/selfie-0123456789abcdef.jpg"
    session.flush()
    assert referenced_keys(session) == {"r1/selfie-0123456789abcdef.jpg"}
