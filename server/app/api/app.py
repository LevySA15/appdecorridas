"""Montagem da aplicação FastAPI. As rotas ficam em `app/api/routes/`; a lógica, nos serviços."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.errors import install_error_handlers
from app.api.routes import admin as admin_routes
from app.api.routes import auth as auth_routes
from app.api.routes import files as files_routes
from app.api.routes import rider as rider_routes


def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
    """`runtime` reúne banco, Redis e adaptadores (ver `app/runtime.py`). `run_background` liga o
    agendador (varreduras de tempo); os testes deixam desligado e chamam as tarefas à mão."""
    dev = getattr(runtime, "mode", "production") == "dev"
    app = FastAPI(
        title="App de corrida do Recôncavo",
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
    )
    app.state.runtime = runtime
    install_error_handlers(app)
    app.include_router(auth_routes.router)
    app.include_router(rider_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(files_routes.router)

    if runtime is not None:

        @app.get("/health")
        def health():
            try:
                runtime.check()
            except Exception:
                return JSONResponse({"status": "down"}, status_code=503)
            return {"status": "ok"}

    return app
