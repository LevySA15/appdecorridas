"""Montagem da aplicação FastAPI. As rotas ficam em `app/api/routes/`; a lógica, nos serviços."""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.errors import install_error_handlers
from app.api.routes import admin as admin_routes
from app.api.routes import auth as auth_routes
from app.api.routes import files as files_routes
from app.api.routes import passenger as passenger_routes
from app.api.routes import payments as payments_routes
from app.api.routes import rider as rider_routes
from app.api.routes import rides as rides_routes
from app.api.routes import safety as safety_routes
from app.api.routes import ws as ws_routes
from app.scheduler import Scheduler


def create_app(runtime=None, *, run_background: bool = False, scheduler: Scheduler | None = None) -> FastAPI:
    """`runtime` reúne banco, Redis e adaptadores (ver `app/runtime.py`). `run_background` liga o
    agendador (varreduras de tempo); os testes deixam desligado e chamam as tarefas à mão."""
    dev = getattr(runtime, "mode", "production") == "dev"

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if run_background and runtime is not None:
            task = asyncio.create_task((scheduler or Scheduler(runtime)).run())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="App de corrida do Recôncavo",
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    install_error_handlers(app)
    app.include_router(auth_routes.router)
    app.include_router(rider_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(files_routes.router)
    app.include_router(passenger_routes.router)
    app.include_router(rides_routes.router)
    app.include_router(payments_routes.router)
    app.include_router(safety_routes.router)
    app.include_router(ws_routes.router)

    if dev:
        from app.api.routes import dev as dev_routes

        app.include_router(dev_routes.router)

    if runtime is not None:

        @app.get("/health")
        def health():
            try:
                runtime.check()
            except Exception:
                return JSONResponse({"status": "down"}, status_code=503)
            return {"status": "ok"}

    return app
