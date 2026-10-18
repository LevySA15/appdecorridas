"""Login por código, sessão e dados da própria conta."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import bearer_token, current_user, get_runtime
from app.api.errors import ApiError
from app.services.auth import AuthUser, TooManyRequests

router = APIRouter(prefix="/v1", tags=["conta"])


class CodeIn(BaseModel):
    phone: str = Field(min_length=8, max_length=30)


class VerifyIn(BaseModel):
    phone: str = Field(min_length=8, max_length=30)
    code: str = Field(min_length=4, max_length=10)
    role: Literal["passenger", "rider", "admin"]
    device: str = Field(default="", max_length=80)


class NameIn(BaseModel):
    name: str = Field(max_length=120)


def user_view(user: AuthUser) -> dict:
    return {"user_id": user.user_id, "phone": user.phone, "name": user.name, "role": user.role}


@router.post("/auth/code", status_code=204)
def request_code(body: CodeIn, request: Request) -> Response:
    runtime = get_runtime(request)
    caller = request.client.host if request.client else "desconhecido"

    def work(unit):
        # contra quem pede código para muitos números (cada envio custa); o limite por número está no serviço
        if not runtime.limiter.hit(f"code-ip:{caller}", unit.cfg.auth.otp_requests_per_ip_hour, 3600, unit.now):
            raise TooManyRequests("Muitos pedidos de código deste aparelho. Tente de novo mais tarde.")
        unit.auth.request_code(unit.session, body.phone, unit.now)

    runtime.run(work)
    return Response(status_code=204)


@router.post("/auth/verify")
def verify_code(body: VerifyIn, request: Request) -> dict:
    def work(unit):
        result = unit.auth.verify_code(unit.session, body.phone, body.code, body.role, body.device, unit.now)
        user = unit.auth.authenticate(unit.session, result.token, unit.now) if result.ok else None
        return result, user

    result, user = get_runtime(request).run(work)     # commit feito: a tentativa errada fica contada
    if not result.ok:
        raise ApiError(401, "code_invalid", result.reason or "Código inválido.")
    return {
        "token": result.token, "user_id": result.user_id, "role": result.role,
        "is_new_user": result.is_new_user, "name": user.name if user else "",
    }


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: AuthUser = Depends(current_user)) -> Response:
    token = bearer_token(request)
    get_runtime(request).run(lambda unit: unit.auth.logout(unit.session, token))
    return Response(status_code=204)


@router.get("/me")
def me(user: AuthUser = Depends(current_user)) -> dict:
    return user_view(user)


@router.put("/me")
def set_name(body: NameIn, request: Request, user: AuthUser = Depends(current_user)) -> dict:
    get_runtime(request).run(lambda unit: unit.auth.set_name(unit.session, user.user_id, body.name))
    return user_view(AuthUser(user.user_id, user.phone, body.name.strip(), user.role))
