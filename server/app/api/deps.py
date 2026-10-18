"""Dependências das rotas: quem está chamando e com qual papel."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from app.api.errors import ApiError
from app.runtime import Runtime
from app.services.auth import AuthUser


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "unauthorized", "Entre de novo para continuar.")
    return token.strip()


def current_user(request: Request) -> AuthUser:
    token = bearer_token(request)
    runtime = get_runtime(request)
    user = runtime.run(lambda unit: unit.auth.authenticate(unit.session, token, unit.now))
    if user is None:
        raise ApiError(401, "unauthorized", "Entre de novo para continuar.")
    return user


def require_role(*roles: str) -> Callable[..., AuthUser]:
    def dependency(user: AuthUser = Depends(current_user)) -> AuthUser:
        if user.role not in roles:
            raise ApiError(403, "wrong_role", "Esta ação não é para o seu tipo de conta.")
        return user

    return dependency


passenger_user = require_role("passenger")
rider_user = require_role("rider")
admin_user = require_role("admin")
