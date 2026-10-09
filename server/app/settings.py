"""Configuração do servidor: variáveis de ambiente, com `server/.env` como reserva.

O arquivo `.env` guarda segredos (senha do banco) e fica fora do git.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str


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

    return Settings(database_url=_with_driver(get("DATABASE_URL")), redis_url=get("REDIS_URL"))
