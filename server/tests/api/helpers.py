"""Ajudantes dos testes da API: entrar com um número e montar o cabeçalho de autorização."""
from dataclasses import dataclass

from app.services.auth import normalize_phone


@dataclass(frozen=True)
class Login:
    user_id: str
    token: str
    phone: str
    role: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def login(client, runtime, phone: str, role: str, name: str | None = None) -> Login:
    resposta = client.post("/v1/auth/code", json={"phone": phone})
    assert resposta.status_code == 204, resposta.text
    codigo = runtime.otp_sender.last_code(normalize_phone(phone))
    resposta = client.post("/v1/auth/verify", json={"phone": phone, "code": codigo, "role": role, "device": "teste"})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    entrou = Login(corpo["user_id"], corpo["token"], normalize_phone(phone), role)
    if name:
        assert client.put("/v1/me", json={"name": name}, headers=entrou.headers).status_code == 200
    return entrou


def rider_phone(n: int) -> str:
    """Celular do motoqueiro que `online_rider(n)` cria (já no formato que o login aceita)."""
    return f"75977{n:06d}"


def online_rider(session, runtime, clock, n: int = 1, point=None) -> str:
    """Motoqueiro aprovado, disponível e com posição fresca. Devolve o id; entra na API com `rider_phone(n)`."""
    from tests.helpers import pt
    from tests.helpers_db import make_online_rider

    return make_online_rider(session, runtime.positions, n, point or pt(300, 0), now=clock.now)
