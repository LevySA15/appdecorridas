"""Ponto de entrada do servidor. Subir (a partir de `server/`):

    .venv/bin/uvicorn --factory app.main:create_default_app --port 8000

Um processo só (`--workers 1`): o hub de WebSocket e o agendador vivem dentro dele.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.app import create_app
from app.runtime import build_runtime
from app.settings import load_settings


def create_default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app(build_runtime(load_settings()), run_background=True)
