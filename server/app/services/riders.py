"""Cadastro, aprovação e disponibilidade do motoqueiro (spec, seções 4 e 8)."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


# O motivo que a varredura de documentos vencidos grava. Quem foi bloqueado pela varredura (e não pelo
# administrador: `UserRow.is_blocked` desligado) volta sozinho ao renovar os documentos.
EXPIRED_DOCUMENTS_REASON = "documento vencido"


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
        # Cadastro recusado pode ser reenviado (decisão do Levy, 25/10/2026): o mesmo cadastro volta a `pending`.
        # A linha é travada, então dois toques seguidos são serializados e o segundo vê `pending`.
        existing = session.execute(
            select(RiderProfileRow).where(RiderProfileRow.user_id == user_id).with_for_update()
        ).scalar_one_or_none()
        if existing is not None and existing.status != "rejected":
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
        duplicate = self._find_duplicate(
            session, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok, exclude_user_id=user_id
        )
        if duplicate is not None:
            raise duplicate
        user.name = clean_name
        try:
            with session.begin_nested():
                if existing is None:
                    session.add(
                        RiderProfileRow(
                            user_id=user_id, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok,
                            moto_model=moto_model.strip(), status="pending", selfie_key=selfie_key,
                            cnh_photo_key=cnh_photo_key, crlv_key=crlv_key,
                            cnh_expires_on=cnh_expires_on, crlv_expires_on=crlv_expires_on,
                        )
                    )
                else:
                    existing.cpf, existing.cnh_number, existing.plate = cpf_ok, cnh_ok, plate_ok
                    existing.moto_model = moto_model.strip()
                    existing.selfie_key, existing.cnh_photo_key, existing.crlv_key = selfie_key, cnh_photo_key, crlv_key
                    existing.cnh_expires_on, existing.crlv_expires_on = cnh_expires_on, crlv_expires_on
                    existing.status, existing.rejected_reason = "pending", None
                session.flush()
        except IntegrityError:
            # Outro cadastro entrou entre a conferência e a gravação (dois toques, duas telas): o banco decide.
            raise self._find_duplicate(
                session, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok, exclude_user_id=user_id
            ) or RegistrationError("Seu cadastro já foi enviado.") from None

    def _find_duplicate(
        self, session: Session, *, cpf: str, cnh_number: str, plate: str, exclude_user_id: str | None = None
    ) -> DuplicateRegistration | None:
        for field, phrase, column, value in (
            ("CPF", "este CPF", RiderProfileRow.cpf, cpf),
            ("número de CNH", "este número de CNH", RiderProfileRow.cnh_number, cnh_number),
            ("placa", "esta placa", RiderProfileRow.plate, plate),
        ):
            query = select(RiderProfileRow.user_id).where(column == value)
            if exclude_user_id is not None:
                query = query.where(RiderProfileRow.user_id != exclude_user_id)   # o próprio cadastro não conta
            if session.execute(query).first() is not None:
                return DuplicateRegistration(field, phrase)
        return None

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
        self,
        session: Session,
        rider_id: str,
        *,
        cnh_expires_on: dt.date,
        crlv_expires_on: dt.date,
        today: dt.date,
        cnh_photo_key: str | None = None,
        crlv_key: str | None = None,
    ) -> None:
        if cnh_expires_on < today or crlv_expires_on < today:
            raise RegistrationError("As novas datas já estão vencidas.")
        profile = self._profile(session, rider_id)
        profile.cnh_expires_on = cnh_expires_on
        profile.crlv_expires_on = crlv_expires_on
        if cnh_photo_key is not None:
            profile.cnh_photo_key = cnh_photo_key
        if crlv_key is not None:
            profile.crlv_key = crlv_key
        user = session.get(UserRow, rider_id)
        if (
            profile.status == "blocked"
            and profile.rejected_reason == EXPIRED_DOCUMENTS_REASON
            and not user.is_blocked
        ):
            profile.status = "approved"
            profile.rejected_reason = None
            self.events.add(rider_id, "rider_unblocked")
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
        account = repo.get_rider_account(session, rider_id)
        reason = offer_block_reason(account, self.fee_cfg)
        if reason == "entrada_pendente":
            raise CannotGoOnline(
                "entry_pending",
                f"Você fez as {self.fee_cfg.trial_rides} corridas de teste. "
                f"Pague a entrada de {brl(self.fee_cfg.entry_fee_cents)} para continuar.",
            )
        if reason == "divida_pendente":
            raise CannotGoOnline(
                "debt_pending",
                f"Você tem uma taxa de {brl(account.cash_debt_cents)} para pagar. Pague para voltar a receber corridas.",
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
            profile.rejected_reason = EXPIRED_DOCUMENTS_REASON
            self.positions.remove(profile.user_id)
            self.events.add(profile.user_id, "documents_expired")
            blocked.append(profile.user_id)
        session.flush()
        return blocked

    def rider_card(self, session: Session, rider_id: str) -> queries.RiderCard:
        return queries.rider_card(session, rider_id)
