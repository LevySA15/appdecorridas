"""Configuração do servidor: variáveis de ambiente, com `server/.env` como reserva.

O arquivo `.env` guarda segredos (senha do banco) e fica fora do git.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_ENV_PATH = _SERVER_DIR / ".env"
_DEFAULT_UPLOAD_DIR = _SERVER_DIR / "var" / "uploads"


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    webhook_secret: str | None = None       # assina os avisos do provedor de pagamento (HMAC)
    upload_dir: Path = _DEFAULT_UPLOAD_DIR  # onde ficam as fotos dos documentos (fora do git)
    mode: str = "production"                # "dev" liga os adaptadores falsos, os únicos que existem até o plano 7
    dev_routes: bool = True                 # "off" não monta /v1/dev/*, /docs e /openapi.json (servidor aberto na internet)
    google_maps_api_key: str | None = None  # com chave, as rotas vêm do Google; sem chave, a estimativa em linha reta
    maps_daily_call_limit: int = 800        # teto de chamadas de rota ao Google por dia (protege a fatura)
    geocode_daily_call_limit: int = 600     # teto de chamadas de endereço escrito ao Google por dia
    maps_travel_mode: str = "DRIVE"         # DRIVE ou TWO_WHEELER (moto; a testar no Brasil)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _with_driver(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


_LIGADO = {"on", "1", "true", "sim"}
_DESLIGADO = {"off", "0", "false", "nao", "não"}


def _parse_switch(name: str, raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    valor = raw.strip().lower()
    if valor in _LIGADO:
        return True
    if valor in _DESLIGADO:
        return False
    raise RuntimeError(f"{name} deve ser on ou off (veio {raw!r})")


_TRAVEL_MODES = ("DRIVE", "TWO_WHEELER")


def _parse_daily_limit(raw: str | None, name: str = "MAPS_DAILY_CALL_LIMIT", default: int | None = None) -> int:
    if raw is None:
        return Settings.maps_daily_call_limit if default is None else default
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value < 1:
        raise RuntimeError(f"{name} deve ser um número inteiro maior que zero (veio {raw!r})")
    return value


def _parse_travel_mode(raw: str | None) -> str:
    if raw is None:
        return Settings.maps_travel_mode
    mode = raw.strip().upper()
    if mode not in _TRAVEL_MODES:
        raise RuntimeError(f"MAPS_TRAVEL_MODE deve ser DRIVE ou TWO_WHEELER (veio {raw!r})")
    return mode


def load_settings(
    env_path: Path | None = None, environ: Mapping[str, str] | None = None
) -> Settings:
    file_values = parse_env_file(env_path or _DEFAULT_ENV_PATH)
    env = os.environ if environ is None else environ

    def get(key: str) -> str:
        value = env.get(key) or file_values.get(key)
        if not value:
            raise RuntimeError(f"falta a configuração {key} (defina no ambiente ou em server/.env)")
        return value

    def optional(key: str) -> str | None:
        return env.get(key) or file_values.get(key) or None

    upload_dir = optional("UPLOAD_DIR")
    dev_routes = _parse_switch("DEV_ROUTES", optional("DEV_ROUTES"), default=True)
    return Settings(
        database_url=_with_driver(get("DATABASE_URL")),
        redis_url=get("REDIS_URL"),
        webhook_secret=optional("WEBHOOK_SECRET"),
        upload_dir=Path(upload_dir) if upload_dir else _DEFAULT_UPLOAD_DIR,
        mode=optional("APP_MODE") or "production",
        dev_routes=dev_routes,
        google_maps_api_key=(optional("GOOGLE_MAPS_API_KEY") or "").strip() or None,
        maps_daily_call_limit=_parse_daily_limit(optional("MAPS_DAILY_CALL_LIMIT")),
        geocode_daily_call_limit=_parse_daily_limit(
            optional("GEOCODE_DAILY_CALL_LIMIT"), "GEOCODE_DAILY_CALL_LIMIT", Settings.geocode_daily_call_limit
        ),
        maps_travel_mode=_parse_travel_mode(optional("MAPS_TRAVEL_MODE")),
    )
