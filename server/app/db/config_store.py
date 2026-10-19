"""Números ajustáveis guardados no banco (tabela `app_config`), com validação ao salvar e ao ler."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import AppConfigRow
from app.domain.config import (
    AuthConfig,
    BalanceConfig,
    DispatchConfig,
    FeeConfig,
    FeeTier,
    PricingConfig,
    RideConfig,
    SafetyConfig,
    validate_balance_config,
    validate_ride_config,
)
from app.domain.fees import validate_fee_config

_TYPES = {
    "pricing": PricingConfig,
    "fees": FeeConfig,
    "rides": RideConfig,
    "dispatch": DispatchConfig,
    "safety": SafetyConfig,
    "auth": AuthConfig,
    "balance": BalanceConfig,
}

# Chaves que existiram e foram retiradas: configuração gravada antes disso ainda carrega, sem elas.
_RETIRED_KEYS = {"rides": {"cancel_compensation_cents"}}


@dataclass(frozen=True)
class AppConfig:
    pricing: PricingConfig
    fees: FeeConfig
    rides: RideConfig
    dispatch: DispatchConfig
    safety: SafetyConfig
    auth: AuthConfig = AuthConfig()
    balance: BalanceConfig = BalanceConfig()

    @classmethod
    def defaults(cls) -> "AppConfig":
        return cls(PricingConfig(), FeeConfig(), RideConfig(), DispatchConfig(), SafetyConfig())


def _check_key(key: str) -> type:
    if key not in _TYPES:
        raise ValueError(f"chave de configuração desconhecida: {key}")
    return _TYPES[key]


def _from_json(key: str, data: dict):
    cls = _check_key(key)
    try:
        data = {k: v for k, v in data.items() if k not in _RETIRED_KEYS.get(key, ())}
        if key == "fees":
            data = {**data, "tiers": tuple(FeeTier(**t) for t in data["tiers"])}
        cfg = cls(**data)
    except (TypeError, KeyError) as exc:
        raise ValueError(f"configuração '{key}' inválida no banco: {exc!r}") from exc
    try:
        _validate(key, cfg)
    except ValueError as exc:
        raise ValueError(f"configuração '{key}' inválida no banco: {exc}") from exc
    return cfg


def _validate(key: str, cfg) -> None:
    if key == "fees":
        validate_fee_config(cfg)
    elif key == "rides":
        validate_ride_config(cfg)
    elif key == "balance":
        validate_balance_config(cfg)


def parse_config(key: str, data: dict):
    """Monta e confere uma configuração vinda de fora (o painel). Erro com frase em português."""
    if key not in _TYPES:
        raise LookupError(f"chave de configuração desconhecida: {key}")
    try:
        return _from_json(key, data)
    except ValueError as exc:
        raise ValueError(str(exc).replace(" no banco", "")) from exc


def all_configs(session: Session) -> dict:
    """Todas as chaves de configuração como dicionários (os padrões onde nada foi gravado)."""
    return {key: asdict(load_config(session, key)) for key in _TYPES}


def save_config(session: Session, key: str, cfg) -> None:
    cls = _check_key(key)
    if not isinstance(cfg, cls):
        raise ValueError(f"tipo errado para '{key}': esperado {cls.__name__}")
    _validate(key, cfg)
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
        auth=load_config(session, "auth"),
        balance=load_config(session, "balance"),
    )
