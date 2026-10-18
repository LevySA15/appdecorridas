"""Ajudantes dos testes da API: entrar com um número e montar o cabeçalho de autorização."""
from dataclasses import dataclass

from app.services.auth import normalize_phone


@dataclass(frozen=True)
class Login:
    user_id: str
    token: str
    phone: str

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
    entrou = Login(corpo["user_id"], corpo["token"], normalize_phone(phone))
    if name:
        assert client.put("/v1/me", json={"name": name}, headers=entrou.headers).status_code == 200
    return entrou
