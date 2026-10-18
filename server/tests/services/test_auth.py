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


def test_pedir_codigo_de_novo_invalida_o_anterior(auth, sender, session):
    # Roteiro do 2B (menores): um código antigo não pode continuar valendo depois de outro ter sido usado.
    auth.request_code(session, PHONE, 1000.0)
    antigo = sender.last_code(NORMAL)
    auth.request_code(session, PHONE, 1010.0)
    novo = sender.last_code(NORMAL)
    assert antigo != novo
    assert auth.verify_code(session, PHONE, novo, "passenger", "x", 1020.0).ok is True
    assert auth.verify_code(session, PHONE, antigo, "passenger", "x", 1030.0).ok is False


def test_administrador_so_entra_se_o_numero_ja_for_de_administrador(auth, sender, session):
    auth.request_code(session, PHONE, 1000.0)
    sem_acesso = auth.verify_code(session, PHONE, sender.last_code(NORMAL), "admin", "painel", 1001.0)
    assert sem_acesso.ok is False and "administrador" in sem_acesso.reason
    assert session.execute(select(UserRow).where(UserRow.phone == NORMAL)).first() is None   # não criou conta

    repo.add_user(session, user_id="adm-1", phone=NORMAL, name="Levy", role="admin")
    auth.request_code(session, PHONE, 2000.0)
    entrou = auth.verify_code(session, PHONE, sender.last_code(NORMAL), "admin", "painel", 2001.0)
    assert entrou.ok and entrou.role == "admin" and entrou.user_id == "adm-1" and not entrou.is_new_user


def test_passageiro_nao_entra_como_administrador(auth, sender, session):
    _login(auth, sender, session, role="passenger")
    resultado = _login(auth, sender, session, now=5000.0, role="admin")
    assert resultado.ok is False and "passageiro" in resultado.reason
