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

from sqlalchemy import func, select, update
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
        # um código só vale por vez: pedir outro invalida o anterior
        session.execute(
            update(OtpCodeRow).where(OtpCodeRow.phone == phone, OtpCodeRow.used.is_(False)).values(used=True)
        )
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
        if role not in ("passenger", "rider", "admin"):
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
        if user is None and role == "admin":      # administrador nunca nasce por login: é criado por `app.cli`
            return LoginResult(False, reason="Este número não tem acesso de administrador.")
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
