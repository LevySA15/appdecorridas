import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api.app import create_app
from app.api.errors import ApiError
from app.domain.payments import PaymentProviderError
from app.domain.rides import InvalidTransition
from app.services.auth import TooManyRequests
from app.services.dispatch import OfferGone
from app.services.quotes import NotAllowed, QuoteExpired
from app.services.riders import CannotGoOnline, DuplicateRegistration, InvalidState, RegistrationError
from app.services.trips import AlreadyRated, NotYourRide


class Corpo(BaseModel):
    lat: float = Field(ge=-90, le=90)


def _client(erro: Exception | None = None) -> TestClient:
    app = create_app(None)

    @app.get("/boom")
    def boom():
        if erro is not None:
            raise erro
        return {"ok": True}

    @app.post("/corpo")
    def corpo(c: Corpo):
        return {"lat": c.lat}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "erro, status, codigo",
    [
        (TooManyRequests("Muitos pedidos."), 429, "too_many_requests"),
        (NotAllowed("Falta pagar a última corrida."), 403, "not_allowed"),
        (QuoteExpired("Esse preço não vale mais."), 409, "quote_expired"),
        (OfferGone("Essa corrida já foi para outro motoqueiro."), 409, "offer_gone"),
        (NotYourRide("Essa corrida não é sua."), 403, "not_your_ride"),
        (AlreadyRated("Você já avaliou esta corrida."), 409, "already_rated"),
        (InvalidTransition("corrida ride-1: estado completed"), 409, "invalid_state"),
        (InvalidState("o cadastro está approved"), 409, "invalid_state"),
        (RegistrationError("Confira a placa da moto."), 422, "invalid"),
        (ValueError("Digite seu nome (de 2 a 120 letras)."), 422, "invalid"),
        (LookupError("corrida ride-1 não encontrada"), 404, "not_found"),
        (PaymentProviderError("timeout"), 503, "payment_unavailable"),
    ],
)
def test_erro_do_servico_vira_resposta_com_codigo_estavel(erro, status, codigo):
    resposta = _client(erro).get("/boom")
    assert resposta.status_code == status
    corpo = resposta.json()["error"]
    assert corpo["code"] == codigo and corpo["message"]


def test_mensagens_tecnicas_nao_vazam_para_o_usuario():
    corpo = _client(InvalidTransition("corrida ride-1: estado completed, esperado in_progress")).get("/boom").json()
    assert "ride-1" not in corpo["error"]["message"]
    corpo = _client(LookupError("corrida ride-1 não encontrada")).get("/boom").json()
    assert "ride-1" not in corpo["error"]["message"]


def test_nao_pode_ficar_disponivel_leva_o_codigo_do_motivo():
    corpo = _client(CannotGoOnline("entry_pending", "Pague a entrada.")).get("/boom").json()["error"]
    assert (corpo["code"], corpo["message"]) == ("entry_pending", "Pague a entrada.")


def test_cadastro_repetido_diz_qual_campo():
    resposta = _client(DuplicateRegistration("CPF", "este CPF")).get("/boom")
    assert resposta.status_code == 409
    assert resposta.json()["error"] == {
        "code": "duplicate_registration", "message": "Já existe um cadastro com este CPF.", "field": "CPF",
    }


def test_erro_explicito_da_rota():
    resposta = _client(ApiError(401, "unauthorized", "Entre de novo.")).get("/boom")
    assert resposta.status_code == 401
    assert resposta.json() == {"error": {"code": "unauthorized", "message": "Entre de novo."}}


def test_corpo_invalido_lista_os_campos_com_problema():
    resposta = _client().post("/corpo", json={"lat": 123})
    assert resposta.status_code == 422
    corpo = resposta.json()["error"]
    assert corpo["code"] == "invalid" and corpo["fields"] == ["lat"]


def test_erro_inesperado_vira_500_generico_sem_detalhe():
    resposta = _client(RuntimeError("senha do banco: 123")).get("/boom")
    assert resposta.status_code == 500
    assert resposta.json() == {"error": {"code": "internal", "message": "Algo deu errado. Tente de novo."}}


def test_keyerror_nao_vira_404_por_engano():
    # KeyError é um LookupError: um erro de programação não pode parecer "não encontrado".
    assert _client(KeyError("x")).get("/boom").status_code == 500


def test_rota_inexistente_e_metodo_errado_usam_o_mesmo_formato():
    cliente = _client()
    assert cliente.get("/nao-existe").json()["error"]["code"] == "http_404"
    assert cliente.post("/boom").json()["error"]["code"] == "http_405"


def test_documentacao_automatica_fica_desligada_fora_do_modo_dev():
    assert _client().get("/docs").status_code == 404
