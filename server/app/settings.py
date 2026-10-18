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
    return Settings(
        database_url=_with_driver(get("DATABASE_URL")),
        redis_url=get("REDIS_URL"),
        webhook_secret=optional("WEBHOOK_SECRET"),
        upload_dir=Path(upload_dir) if upload_dir else _DEFAULT_UPLOAD_DIR,
        mode=optional("APP_MODE") or "production",
    )
