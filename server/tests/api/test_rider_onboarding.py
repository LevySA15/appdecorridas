import datetime as dt

import pytest

from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from app.domain.clock import local_date
from app.infra.documents import MAX_UPLOAD_BYTES
from tests.api.helpers import login
from tests.helpers_db import make_cpf

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
CPF = make_cpf("123456789")


def subir(client, quem, kind, dados=JPEG):
    resposta = client.put(f"/v1/rider/documents/{kind}", content=dados, headers=quem.headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["key"]


def cadastro(client, quem, hoje, **mudar):
    corpo = dict(
        name="Carlos Moto", cpf=CPF, cnh_number="12345678901", plate="abc-1d23", moto_model="Honda CG 160",
        cnh_expires_on=str(hoje + dt.timedelta(days=700)), crlv_expires_on=str(hoje + dt.timedelta(days=300)),
    )
    corpo.update(mudar)
    for campo, kind in (("selfie_key", "selfie"), ("cnh_photo_key", "cnh"), ("crlv_key", "crlv")):
        if campo not in corpo:
            corpo[campo] = subir(client, quem, kind) if quem.role == "rider" else f"x/{kind}-0123456789abcdef.jpg"
    return client.post("/v1/rider/register", json=corpo, headers=quem.headers)


@pytest.fixture()
def hoje(clock):
    return local_date(clock.now)


@pytest.fixture()
def rider(client, runtime):
    return login(client, runtime, "75 99999-0002", "rider")


@pytest.fixture()
def admin(client, runtime, session):
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    return login(client, runtime, "75 99999-0000", "admin")


# --- envio de documentos ---------------------------------------------------------------------


def test_envia_a_foto_e_recebe_uma_chave_do_proprio_motoqueiro(client, rider):
    chave = subir(client, rider, "selfie")
    assert chave.startswith(f"{rider.user_id}/selfie-")


def test_so_motoqueiro_envia_documento(client, runtime):
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    resposta = client.put("/v1/rider/documents/selfie", content=JPEG, headers=passageiro.headers)
    assert resposta.status_code == 403
    assert client.put("/v1/rider/documents/selfie", content=JPEG).status_code == 401


@pytest.mark.parametrize(
    "dados, status, codigo",
    [
        (b"<html>oi</html>", 415, "not_an_image"),
        (b"", 422, "empty_file"),
        (b"%PDF-1.4 ...", 415, "not_an_image"),
    ],
)
def test_arquivo_que_nao_e_foto_e_recusado(client, rider, dados, status, codigo):
    resposta = client.put("/v1/rider/documents/cnh", content=dados, headers=rider.headers)
    assert resposta.status_code == status and resposta.json()["error"]["code"] == codigo


def test_arquivo_grande_demais_e_recusado_sem_guardar(client, rider, runtime, tmp_path):
    grande = JPEG + b"0" * MAX_UPLOAD_BYTES
    resposta = client.put("/v1/rider/documents/cnh", content=grande, headers=rider.headers)
    assert resposta.status_code == 413 and resposta.json()["error"]["code"] == "file_too_large"
    assert list(runtime.documents.root.rglob("*.jpg")) == []


def test_arquivo_grande_demais_sem_tamanho_declarado_tambem_e_cortado(client, rider):
    def pedacos():
        yield JPEG
        for _ in range(9):
            yield b"0" * (1024 * 1024)

    resposta = client.put("/v1/rider/documents/cnh", content=pedacos(), headers=rider.headers)
    assert resposta.status_code == 413


def test_tipo_de_documento_invalido_e_422(client, rider):
    assert client.put("/v1/rider/documents/senha", content=JPEG, headers=rider.headers).status_code == 422


def test_limite_de_envios_por_hora(client, rider, clock):
    for _ in range(30):
        subir(client, rider, "selfie")
    resposta = client.put("/v1/rider/documents/selfie", content=JPEG, headers=rider.headers)
    assert resposta.status_code == 429
    clock.advance(3600)
    assert client.put("/v1/rider/documents/selfie", content=JPEG, headers=rider.headers).status_code == 201


# --- cadastro --------------------------------------------------------------------------------


def test_cadastro_fica_pendente_e_guarda_os_dados_limpos(client, rider, session, hoje):
    resposta = cadastro(client, rider, hoje)
    assert resposta.status_code == 201 and resposta.json() == {"status": "pending"}
    perfil = session.get(RiderProfileRow, rider.user_id)
    assert (perfil.status, perfil.plate, perfil.online) == ("pending", "ABC1D23", False)
    assert session.get(UserRow, rider.user_id).name == "Carlos Moto"


def test_cadastro_com_dado_ruim_diz_o_que_conferir(client, rider, hoje):
    resposta = cadastro(client, rider, hoje, cpf="123.456.789-00")
    assert resposta.status_code == 422 and "CPF" in resposta.json()["error"]["message"]
    resposta = cadastro(client, rider, hoje, plate="XX")
    assert "placa" in resposta.json()["error"]["message"]


def test_cadastro_exige_fotos_enviadas_pelo_proprio_motoqueiro(client, runtime, rider, hoje):
    outro = login(client, runtime, "75 99999-0003", "rider")
    chave_do_outro = subir(client, outro, "selfie")
    resposta = cadastro(client, rider, hoje, selfie_key=chave_do_outro)
    assert resposta.status_code == 422 and "selfie" in resposta.json()["error"]["message"].lower()
    resposta = cadastro(client, rider, hoje, crlv_key=f"{rider.user_id}/crlv-0123456789abcdef.jpg")   # não existe
    assert resposta.status_code == 422
    resposta = cadastro(client, rider, hoje, cnh_photo_key=subir(client, rider, "selfie"))            # tipo trocado
    assert resposta.status_code == 422


def test_cadastro_repetido_do_mesmo_cpf_diz_o_campo(client, runtime, rider, hoje):
    assert cadastro(client, rider, hoje).status_code == 201
    outro = login(client, runtime, "75 99999-0003", "rider")
    resposta = cadastro(client, outro, hoje, cnh_number="99999999999", plate="ZZZ9Z99")
    assert resposta.status_code == 409
    assert resposta.json()["error"] == {
        "code": "duplicate_registration", "message": "Já existe um cadastro com este CPF.", "field": "CPF",
    }


def test_cadastro_so_uma_vez_e_so_de_motoqueiro(client, runtime, rider, hoje):
    assert cadastro(client, rider, hoje).status_code == 201
    assert cadastro(client, rider, hoje).status_code == 422
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    assert cadastro(client, passageiro, hoje).status_code == 403


# --- aprovação pelo administrador ------------------------------------------------------------


def test_so_administrador_ve_e_decide_cadastros(client, rider, hoje):
    cadastro(client, rider, hoje)
    assert client.get("/v1/admin/riders", headers=rider.headers).status_code == 403
    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=rider.headers).status_code == 403
    assert client.get("/v1/admin/riders").status_code == 401


def test_fila_de_cadastros_aprovar_recusar_bloquear_e_liberar(client, runtime, rider, admin, hoje, session, listen):
    avisos = listen(rider.user_id)
    cadastro(client, rider, hoje)
    fila = client.get("/v1/admin/riders", params={"status": "pending"}, headers=admin.headers).json()
    assert [r["rider_id"] for r in fila] == [rider.user_id]
    assert fila[0]["name"] == "Carlos Moto" and fila[0]["plate"] == "ABC1D23" and fila[0]["status"] == "pending"
    assert fila[0]["cpf"] == f"{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}"
    assert set(fila[0]["documents"]) == {"selfie", "cnh", "crlv"}

    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).status == "approved"
    assert avisos.types == ["rider_approved"]                       # o aviso sai depois do commit
    assert client.get("/v1/admin/riders", params={"status": "pending"}, headers=admin.headers).json() == []

    resposta = client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"

    corpo = {"reason": "Documento ilegível"}
    assert client.post(f"/v1/admin/riders/{rider.user_id}/block", json=corpo, headers=admin.headers).status_code == 204
    assert client.get("/v1/me", headers=rider.headers).status_code == 401      # bloqueado perde o acesso
    assert client.post(f"/v1/admin/riders/{rider.user_id}/unblock", headers=admin.headers).status_code == 204
    assert client.get("/v1/me", headers=rider.headers).status_code == 200


def test_recusar_cadastro_guarda_o_motivo(client, rider, admin, hoje, session):
    cadastro(client, rider, hoje)
    resposta = client.post(
        f"/v1/admin/riders/{rider.user_id}/reject", json={"reason": "CNH vencida na foto"}, headers=admin.headers
    )
    assert resposta.status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).rejected_reason == "CNH vencida na foto"
    sem_motivo = client.post(f"/v1/admin/riders/{rider.user_id}/reject", json={"reason": ""}, headers=admin.headers)
    assert sem_motivo.status_code == 422


def test_motoqueiro_recusado_reenvia_o_cadastro_pela_api(client, rider, admin, hoje):
    assert cadastro(client, rider, hoje).status_code == 201
    recusa = client.post(
        f"/v1/admin/riders/{rider.user_id}/reject", json={"reason": "Foto da CNH ilegível"}, headers=admin.headers
    )
    assert recusa.status_code == 204
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "rejected"
    assert estado["registration"]["reason"] == "Foto da CNH ilegível"

    novo = cadastro(client, rider, hoje, name="Carlos Moto Novo")

    assert (novo.status_code, novo.json()) == (201, {"status": "pending"})
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "pending"
    assert estado["registration"]["reason"] is None


def test_decidir_motoqueiro_que_nao_existe_e_404(client, admin):
    assert client.post("/v1/admin/riders/ninguem/approve", headers=admin.headers).status_code == 404


def test_lista_do_administrador_filtra_por_situacao_e_pagina(client, runtime, rider, admin, hoje):
    cadastro(client, rider, hoje)
    assert client.get("/v1/admin/riders", params={"status": "approved"}, headers=admin.headers).json() == []
    assert client.get("/v1/admin/riders", params={"status": "qualquer"}, headers=admin.headers).status_code == 422
    assert client.get("/v1/admin/riders", params={"limit": 0}, headers=admin.headers).status_code == 422
    assert client.get("/v1/admin/riders", params={"offset": 5}, headers=admin.headers).json() == []


# --- documentos vencidos e renovação ----------------------------------------------------------


def test_renovar_documentos_troca_datas_e_fotos(client, rider, hoje, session):
    cadastro(client, rider, hoje)
    nova = subir(client, rider, "cnh")
    corpo = {
        "cnh_expires_on": str(hoje + dt.timedelta(days=900)), "crlv_expires_on": str(hoje + dt.timedelta(days=400)),
        "cnh_photo_key": nova,
    }
    assert client.post("/v1/rider/documents/renew", json=corpo, headers=rider.headers).status_code == 204
    perfil = session.get(RiderProfileRow, rider.user_id)
    assert perfil.cnh_photo_key == nova and perfil.cnh_expires_on == hoje + dt.timedelta(days=900)


def test_renovar_com_data_vencida_ou_foto_alheia_e_recusado(client, runtime, rider, hoje):
    cadastro(client, rider, hoje)
    vencida = {"cnh_expires_on": str(hoje - dt.timedelta(days=1)), "crlv_expires_on": str(hoje + dt.timedelta(days=9))}
    assert client.post("/v1/rider/documents/renew", json=vencida, headers=rider.headers).status_code == 422
    outro = login(client, runtime, "75 99999-0003", "rider")
    alheia = {
        "cnh_expires_on": str(hoje + dt.timedelta(days=9)), "crlv_expires_on": str(hoje + dt.timedelta(days=9)),
        "crlv_key": subir(client, outro, "crlv"),
    }
    assert client.post("/v1/rider/documents/renew", json=alheia, headers=rider.headers).status_code == 422


# --- ver os documentos ------------------------------------------------------------------------


def test_quem_pode_ver_cada_documento(client, runtime, rider, admin, hoje, session):
    cadastro(client, rider, hoje)
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    outro_motoqueiro = login(client, runtime, "75 99999-0003", "rider")
    url = f"/v1/riders/{rider.user_id}/documents"

    for quem in (admin, rider):
        for kind in ("selfie", "cnh", "crlv"):
            resposta = client.get(f"{url}/{kind}", headers=quem.headers)
            assert resposta.status_code == 200 and resposta.content == JPEG
            assert resposta.headers["content-type"] == "image/jpeg"
            assert resposta.headers["cache-control"] == "private, max-age=3600"
            assert resposta.headers["x-content-type-options"] == "nosniff"

    # passageiro sem corrida com este motoqueiro, outro motoqueiro e visitante: nada
    assert client.get(f"{url}/selfie", headers=passageiro.headers).status_code == 403
    assert client.get(f"{url}/selfie", headers=outro_motoqueiro.headers).status_code == 403
    assert client.get(f"{url}/selfie").status_code == 401

    # passageiro que fez corrida com ele vê só a selfie, nunca a CNH nem o documento da moto
    from app.db.models import RideRow

    session.add(
        RideRow(
            id="ride-1", passenger_id=passageiro.user_id, rider_id=rider.user_id, price_cents=700,
            payment_method="cash", pin="1234", state="completed",
        )
    )
    session.flush()
    assert client.get(f"{url}/selfie", headers=passageiro.headers).status_code == 200
    assert client.get(f"{url}/cnh", headers=passageiro.headers).status_code == 403
    assert client.get(f"{url}/crlv", headers=passageiro.headers).status_code == 403


def test_documento_de_quem_nao_se_cadastrou_e_404(client, admin, rider):
    assert client.get(f"/v1/riders/{rider.user_id}/documents/selfie", headers=admin.headers).status_code == 404
    assert client.get("/v1/riders/ninguem/documents/selfie", headers=admin.headers).status_code == 404
