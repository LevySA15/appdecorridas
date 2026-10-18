"""Servidor descartável para a simulação e para os testes de ponta a ponta.

Cria um esquema só dele no PostgreSQL de desenvolvimento (nunca mexe no `public`), usa um banco numerado do Redis
(esvaziado no fim) e uma pasta temporária para as fotos. Sobe o servidor de verdade (uvicorn) e, ao sair, apaga tudo.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx2 as httpx
import redis
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.cli import create_admin
from app.db.config_store import save_config
from app.domain.config import AuthConfig, DispatchConfig, RideConfig, SafetyConfig
from app.settings import load_settings

SERVER_DIR = Path(__file__).resolve().parents[1]
ADMIN_PHONE = "75 99999-0000"
WEBHOOK_SECRET = "segredo-do-simulador"


def seed_database(session: Session, *, fast: bool) -> None:
    """Solta os limites de pedido de código (a simulação entra com dezenas de pessoas do mesmo aparelho) e cria o administrador.

    Com `fast`, encurta os prazos do servidor (Pix, espera, procura, aviso de parada) para a simulação mostrar tudo em minutos.
    """
    save_config(session, "auth", AuthConfig(otp_requests_per_hour=1000, otp_requests_per_ip_hour=1_000_000))
    if fast:
        save_config(
            session, "rides",
            dataclasses.replace(
                RideConfig(), pix_window_s=40, max_wait_at_arrival_s=75, queue_max_wait_s=120, search_give_up_s=45,
                cash_pay_wait_s=45, free_cancel_after_accept_s=15,
            ),
        )
        save_config(session, "dispatch", dataclasses.replace(DispatchConfig(), offer_timeout_s=8))
        save_config(
            session, "safety", dataclasses.replace(SafetyConfig(), stopped_after_s=40, alert_cooldown_s=120)
        )
    create_admin(session, ADMIN_PHONE, "Levy (sim)")
    session.commit()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Sandbox:
    def __init__(self, *, fast: bool = False, redis_db: int = 14) -> None:
        self.fast = fast
        self.redis_db = redis_db
        self.url = ""
        self.schema = ""
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> Sandbox:
        settings = load_settings()
        self.schema = f"t_{uuid.uuid4().hex[:10]}"
        self._admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
        with self._admin.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        try:
            self._start(settings)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _start(self, settings) -> None:
        engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={self.schema},public"})
        cfg = Config(str(SERVER_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            cfg.attributes["schema"] = self.schema
            command.upgrade(cfg, "head")
        with Session(engine) as session:
            seed_database(session, fast=self.fast)
        engine.dispose()
        self._uploads = tempfile.mkdtemp(prefix="sim-uploads-")
        self._redis_url = settings.redis_url.rsplit("/", 1)[0] + f"/{self.redis_db}"
        separator = "&" if "?" in settings.database_url else "?"
        env = dict(
            os.environ,
            DATABASE_URL=settings.database_url + separator + "options=" + quote(f"-csearch_path={self.schema},public"),
            REDIS_URL=self._redis_url, APP_MODE="dev", WEBHOOK_SECRET=WEBHOOK_SECRET, UPLOAD_DIR=self._uploads,
        )
        port = _free_port()
        self._log_path = Path(self._uploads) / "servidor.log"
        self._log = open(self._log_path, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", "app.main:create_default_app", "--port", str(port),
             "--log-level", "warning"],
            cwd=SERVER_DIR, env=env, stdout=self._log, stderr=subprocess.STDOUT, text=True,
        )
        self.url = f"http://127.0.0.1:{port}"
        for _ in range(120):
            if self.process.poll() is not None:
                raise RuntimeError("o servidor descartável caiu ao subir:\n" + self.log_text())
            try:
                if httpx.get(self.url + "/health", timeout=1).status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.25)
        raise RuntimeError("o servidor descartável não subiu em 30 s:\n" + self.log_text())

    def log_text(self) -> str:
        self._log.flush()
        return self._log_path.read_text(encoding="utf-8", errors="replace")

    def problems(self) -> list[str]:
        """Linhas do registro do servidor que indicam erro de verdade."""
        return [
            line for line in self.log_text().splitlines()
            if "Traceback" in line or " ERROR " in line or line.startswith("ERROR")
        ]

    def retries(self) -> int:
        """Quantas vezes o servidor repetiu uma operação porque o banco derrubou a transação por impasse."""
        return sum(1 for line in self.log_text().splitlines() if "transação repetida" in line)

    def __exit__(self, *exc) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if getattr(self, "_log", None) is not None:
            self._log.flush()
        with self._admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        self._admin.dispose()
        if getattr(self, "_redis_url", None):
            redis.Redis.from_url(self._redis_url).flushdb()
        if getattr(self, "_log", None) is not None:
            self._log.close()
        shutil.rmtree(getattr(self, "_uploads", ""), ignore_errors=True)
