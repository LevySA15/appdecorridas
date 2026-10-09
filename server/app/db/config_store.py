"""Números ajustáveis guardados no banco (tabela `app_config`), com validação ao salvar e ao ler."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import AppConfigRow
from app.domain.config import (
    DispatchConfig,
    FeeConfig,
    FeeTier,
    PricingConfig,
    RideConfig,
    SafetyConfig,
)
from app.domain.fees import validate_fee_config

_TYPES = {
    "pricing": PricingConfig,
    "fees": FeeConfig,
    "rides": RideConfig,
    "dispatch": DispatchConfig,
    "safety": SafetyConfig,
}


@dataclass(frozen=True)
class AppConfig:
    pricing: PricingConfig
    fees: FeeConfig
    rides: RideConfig
    dispatch: DispatchConfig
    safety: SafetyConfig


def _check_key(key: str) -> type:
    if key not in _TYPES:
        raise ValueError(f"chave de configuração desconhecida: {key}")
    return _TYPES[key]


def _from_json(key: str, data: dict):
    cls = _check_key(key)
    try:
        if key == "fees":
            data = {**data, "tiers": tuple(FeeTier(**t) for t in data["tiers"])}
        cfg = cls(**data)
    except (TypeError, KeyError) as exc:
        raise ValueError(f"configuração '{key}' inválida no banco: {exc!r}") from exc
    if key == "fees":
        try:
            validate_fee_config(cfg)
        except ValueError as exc:
            raise ValueError(f"configuração 'fees' inválida no banco: {exc}") from exc
    return cfg


def save_config(session: Session, key: str, cfg) -> None:
    cls = _check_key(key)
    if not isinstance(cfg, cls):
        raise ValueError(f"tipo errado para '{key}': esperado {cls.__name__}")
    if key == "fees":
        validate_fee_config(cfg)
    value = asdict(cfg)
    stmt = pg_insert(AppConfigRow).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": value, "updated_at": func.now()}
    )
    session.execute(stmt)


def load_config(session: Session, key: str):
    cls = _check_key(key)
    data = session.execute(select(AppConfigRow.value).where(AppConfigRow.key == key)).scalar_one_or_none()
    if data is None:
        return cls()
    return _from_json(key, data)


def load_app_config(session: Session) -> AppConfig:
    return AppConfig(
        pricing=load_config(session, "pricing"),
        fees=load_config(session, "fees"),
        rides=load_config(session, "rides"),
        dispatch=load_config(session, "dispatch"),
        safety=load_config(session, "safety"),
    )
