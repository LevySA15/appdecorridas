"""Limpeza das fotos de documentos que ninguém mais usa (LGPD: guardar só o que tem motivo).

Duas regras (prazos para o advogado conferir; ver o plano 4F):
- foto de cadastro **recusado** é apagada 30 dias depois da recusa (o cadastro e o motivo ficam);
- foto que nenhum cadastro usa (trocada num reenvio ou numa renovação, ou enviada e abandonada) é apagada
  24 horas depois do envio.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RiderProfileRow
from app.infra.documents import DocumentStore

log = logging.getLogger("app.document_cleanup")

ORPHAN_AFTER_S = 24 * 3600.0
REJECTED_KEEP_S = 30 * 24 * 3600.0

_PHOTO_COLUMNS = ("selfie_key", "cnh_photo_key", "crlv_key")


@dataclass(frozen=True)
class PurgeReport:
    rejected: int       # fotos de cadastro recusado apagadas
    orphans: int        # fotos sem dono apagadas
    partials: int = 0   # envios pela metade (arquivos .part parados há mais de 1 hora) apagados


def release_rejected_photos(session: Session, now: float) -> list[str]:
    """Desliga as fotos dos cadastros recusados há mais de `REJECTED_KEEP_S` e devolve as chaves para apagar
    do disco (depois do commit). Só mexe em `rejected` com hora de recusa: os outros nunca perdem foto aqui."""
    rows = session.execute(
        select(RiderProfileRow)
        .where(
            RiderProfileRow.status == "rejected",
            RiderProfileRow.rejected_at.is_not(None),
            RiderProfileRow.rejected_at <= now - REJECTED_KEEP_S,
        )
        .order_by(RiderProfileRow.user_id)
        .with_for_update()
    ).scalars().all()
    keys: list[str] = []
    for profile in rows:
        for column in _PHOTO_COLUMNS:
            key = getattr(profile, column)
            if key:
                keys.append(key)
                setattr(profile, column, None)
    session.flush()
    return keys


def referenced_keys(session: Session) -> set[str]:
    """Toda foto que algum cadastro ainda usa."""
    rows = session.execute(
        select(RiderProfileRow.selfie_key, RiderProfileRow.cnh_photo_key, RiderProfileRow.crlv_key)
    ).all()
    return {key for row in rows for key in row if key}


def delete_unreferenced(store: DocumentStore, referenced: set[str], now: float) -> int:
    """Apaga as fotos fora de `referenced` com mais de `ORPHAN_AFTER_S`. Erro num arquivo não impede os outros."""
    deleted = 0
    for item in store.list_all():
        if item.key in referenced or item.modified_at > now - ORPHAN_AFTER_S:
            continue
        try:
            store.delete(item.key)
        except Exception:
            log.warning("não consegui apagar %s; tento de novo amanhã", item.key, exc_info=True)
            continue
        deleted += 1
    return deleted
