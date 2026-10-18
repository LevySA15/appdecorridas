"""Tradução dos erros dos serviços em respostas HTTP.

Toda resposta de erro tem a mesma forma: `{"error": {"code": ..., "message": ...}}`. O `code` é estável
(os apps decidem o que mostrar por ele); a `message` é uma frase em português para a pessoa. Erros de
programação nunca vazam detalhe: viram 500 com mensagem genérica.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.payments import PaymentProviderError
from app.infra.documents import UploadError
from app.domain.rides import InvalidTransition, WrongPin
from app.services.auth import TooManyRequests
from app.services.dispatch import OfferGone
from app.services.quotes import NotAllowed, QuoteExpired
from app.services.riders import CannotGoOnline, DuplicateRegistration, InvalidState, RegistrationError
from app.services.safety import AlertClosed
from app.services.trips import AlreadyRated, NotYourRide


class ApiError(Exception):
    """Erro escolhido pela própria rota (por exemplo, "entre de novo")."""

    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


@dataclass(frozen=True)
class _Rule:
    status: int
    code: str
    message: str | None = None      # frase fixa; sem ela vale o texto do próprio erro (já escrito para a pessoa)


# Erros de domínio com texto técnico usam frase fixa; os demais já trazem uma frase para a pessoa.
_RULES: dict[type[Exception], _Rule] = {
    TooManyRequests: _Rule(429, "too_many_requests"),
    NotAllowed: _Rule(403, "not_allowed"),
    QuoteExpired: _Rule(409, "quote_expired"),
    OfferGone: _Rule(409, "offer_gone"),
    NotYourRide: _Rule(403, "not_your_ride"),
    AlreadyRated: _Rule(409, "already_rated"),
    AlertClosed: _Rule(409, "alert_closed"),
    InvalidTransition: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual da corrida."),
    InvalidState: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual do cadastro."),
    WrongPin: _Rule(422, "wrong_pin", "Código errado. Confira os 4 dígitos com o passageiro."),
    RegistrationError: _Rule(422, "invalid"),
    ValueError: _Rule(422, "invalid"),
}

PIX_DOWN_FOR_S = 60.0

INTERNAL_MESSAGE = "Algo deu errado. Tente de novo."


def error_response(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


def _rule_handler(rule: _Rule):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response(rule.status, rule.code, rule.message or str(exc) or rule.code)

    return handler


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, **exc.extra)


async def _cannot_go_online(request: Request, exc: CannotGoOnline) -> JSONResponse:
    return error_response(409, exc.code, exc.message)


async def _payment_unavailable(request: Request, exc: PaymentProviderError) -> JSONResponse:
    # Desde já, e por um minuto, o app passa a oferecer só dinheiro (spec, seção 12).
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None:
        runtime.pix_health.mark_down(runtime.clock(), PIX_DOWN_FOR_S)
    return error_response(503, "payment_unavailable", "O Pix está instável agora. Tente de novo em instantes.")


async def _upload_error(request: Request, exc: UploadError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message)


async def _duplicate_registration(request: Request, exc: DuplicateRegistration) -> JSONResponse:
    return error_response(409, "duplicate_registration", str(exc), field=exc.field)


async def _not_found(request: Request, exc: LookupError) -> JSONResponse:
    if type(exc) is not LookupError:      # KeyError e IndexError são defeitos de programação, não "não encontrado"
        raise exc
    return error_response(404, "not_found", "Não encontramos o que você procura.")


async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        ".".join(str(part) for part in err["loc"] if part not in ("body", "query", "path"))
        for err in exc.errors()
    ]
    return error_response(422, "invalid", "Confira os dados enviados.", fields=fields)


_HTTP_MESSAGES = {404: "Não encontramos o que você procura.", 405: "Essa ação não existe."}


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = _HTTP_MESSAGES.get(exc.status_code) or str(exc.detail)
    return error_response(exc.status_code, f"http_{exc.status_code}", message)


async def _internal(request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "internal", INTERNAL_MESSAGE)


def install_error_handlers(app: FastAPI) -> None:
    for exc_class, rule in _RULES.items():
        app.add_exception_handler(exc_class, _rule_handler(rule))
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(CannotGoOnline, _cannot_go_online)
    app.add_exception_handler(UploadError, _upload_error)
    app.add_exception_handler(PaymentProviderError, _payment_unavailable)
    app.add_exception_handler(DuplicateRegistration, _duplicate_registration)
    app.add_exception_handler(LookupError, _not_found)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _internal)
