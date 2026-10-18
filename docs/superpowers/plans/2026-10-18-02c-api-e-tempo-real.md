# API e tempo real — Plano de implementação (plano 2C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar o motor de corrida do plano 2B na rua: uma API HTTP + WebSocket (FastAPI) para os apps do passageiro e do motoqueiro, o aviso assinado do provedor de pagamento, o agendador das varreduras de tempo e da checagem diária, os alertas de segurança com SOS e o envio de documentos, tudo em modo de desenvolvimento (adaptadores falsos) até o plano 7.

**Architecture:** As rotas são finas: cada uma chama `Runtime.run(trabalho)`, que abre uma sessão, monta os serviços do 2B com **um** `EventCollector` só para aquele pedido, grava (`commit`) e **só depois** publica os avisos no hub do WebSocket; erro desfaz o banco e descarta os avisos; impasse no banco repete o pedido. O WebSocket só entrega dicas; a fonte da verdade é o endpoint de estado de cada papel, que o app consulta ao abrir e ao reconectar. O agendador roda dentro do mesmo processo (um processo só) e usa as mesmas peças. O Pix e o resto do mundo de fora continuam falsos (`APP_MODE=dev`).

**Tech Stack:** Python 3.12, FastAPI + uvicorn[standard] (WebSocket), Pydantic 2 (vem com o FastAPI), SQLAlchemy 2.x, psycopg 3, Alembic, redis-py, pytest, `httpx2` (só para o `TestClient`). Nenhuma outra biblioteca nova.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 4, 5, 8, 9, 10.1, 10.2, 10.4 e 12). Este é o plano 2C de 10; ver `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`. Parte do estado de `main` depois do plano 2B (commit `b5e1d72`, 381 testes).

**Como este plano foi escrito:** todo o código abaixo foi escrito e rodado numa cópia descartável do servidor, tarefa por tarefa, com os testes primeiro: 682 testes passam, o cenário de um dia inteiro pela API fecha o livro-caixa, e o servidor foi subido de verdade (uvicorn, WebSocket real). Os trechos de **arquivo novo** são o arquivo inteiro; os de **arquivo que já existe** são mostrados como diff (linhas com `-` saem, linhas com `+` entram, o resto é contexto) e podem ser aplicados à mão ou salvos num arquivo e aplicados com `git apply` a partir da raiz do repositório. Os resultados em `Expected:` foram medidos nessa cópia.

## Global Constraints

- Dinheiro sempre em **centavos inteiros**. Tempos em segundos (`float`, época Unix); datas `AAAA-MM-DD`; coordenadas `{"lat", "lng"}`. Telefones guardados como `+55DDD9XXXXXXXX`.
- Serviços e repositórios **não fazem `commit`**. Rotas e tarefas usam `Runtime.run` (ou `sweep_once`). Avisos só saem **depois** do commit; cada unidade de trabalho tem o seu `EventCollector`, nunca um global.
- Ordem de travas no banco: corrida → corrida da fila → motoqueiro → cobrança → passageiro. `save_rider_account` só depois de ler a conta com `for_update=True`.
- O cliente Redis é sempre criado com `decode_responses=True`.
- Resposta de erro sempre `{"error": {"code", "message"}}`; `code` estável em inglês, `message` uma frase curta em português do Brasil, sem culpar o usuário e **sem detalhe interno** (nomes de tabela, ids de corrida, texto de exceção). Erro de programação vira 500 genérico.
- Token só no cabeçalho `Authorization: Bearer` ou na primeira mensagem do WebSocket; nunca na URL. Segredos só em `server/.env`, que o git ignora.
- Foto de documento: JPEG, PNG ou WebP, até 8 MB, tipo conferido pelo conteúdo, guardada fora do git (`server/var/uploads`) com permissão só do dono.
- Aviso do provedor de pagamento: assinatura HMAC-SHA256 do corpo com `WEBHOOK_SECRET`; valor e corrida conferidos com a cobrança guardada antes de aplicar; cada `event_id` é tratado uma vez só.
- **Um processo só** (`--workers 1`): o hub do WebSocket e o agendador vivem dentro dele.
- Sem `APP_MODE=dev` o servidor recusa subir (os adaptadores reais são do plano 7). As rotas `/v1/dev/*` e `/docs` só existem em modo dev.
- Os testes usam o esquema temporário `t_<aleatório>` no banco de desenvolvimento e o Redis banco 15 (o script de fumaça usa o banco 14).
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Todos os comandos partem da pasta `server/` (a Tarefa 13 também mexe em `docs/` e `.gitignore`, na raiz). `systemctl is-active postgresql redis-server` deve responder `active` duas vezes.

## Review Focus

1. **Aviso antes do commit, ou de pedido desfeito:** nenhum app pode ser avisado de algo que o banco não guardou (erro no meio do pedido, impasse repetido, varredura de uma corrida que falha). Testes: Tarefa 4 (`test_o_commit_vem_antes_da_publicacao`, `test_erro_no_meio_desfaz_o_banco_e_nao_publica_nada`, `test_impasse_no_banco_repete_a_unidade_com_avisos_novos`) e Tarefa 11 (`test_corrida_com_erro_nao_impede_as_outras_e_seus_avisos_nao_saem`).
2. **Aviso do provedor de pagamento:** assinatura falsa ou ausente, corpo alterado depois de assinado, valor ou corrida diferentes da cobrança, cobrança desconhecida, aviso repetido, corpo ilegível ou gigante, Pix pago depois de a corrida ser cancelada (deve voltar o dinheiro e avisar). Tarefa 9.
3. **App que volta de uma queda:** o estado de cada papel precisa trazer sozinho tudo para redesenhar a tela (oferta pendente, corrida andando, fila com "onde a moto termina e quando chega", pagamento esperado, bloqueio, Pix a pagar). Tarefas 7, 8 e 12.
4. **Fotos de documento:** o que não é imagem, arquivo grande demais (com e sem tamanho declarado), chave de foto de outro motoqueiro ou de outro tipo no cadastro, e quem pode ver cada foto (passageiro só a selfie de quem já o buscou). Tarefa 6.
5. **Segurança durante a corrida:** aviso repetido a cada posição, SOS sem contato cadastrado ou com o contato fora do ar, SOS apertado várias vezes, código de 4 dígitos adivinhado no tapa, posição com salto impossível (localização falsa). Tarefas 8 e 10.

## Decisões deste plano (o Levy confere)

Tomei estas decisões porque a spec não fecha cada detalhe; cada uma tem custo baixo de trocar:

1. **A API traz o mínimo do painel para o fluxo andar:** fila de cadastros, aprovar, recusar, bloquear, liberar, ver as fotos, e a lista de alertas de segurança. O restante do painel (corridas, dinheiro, devedores, parâmetros) é o plano 4.
2. **Posição do motoqueiro por requisição comum a cada ~4 s, não pelo WebSocket.** Mais simples de testar e de reenviar depois de uma queda. O WebSocket só entrega avisos (servidor para o app).
3. **O WebSocket é só uma dica.** Perdeu a conexão ou a fila encheu: o servidor fecha (código 4408) e o app pede o estado de novo. Não guardo avisos para repetir depois.
4. **O aviso do provedor tem um formato interno assinado** (`x-signature`). A Woovi real (plano 7) ganha um adaptador que traduz o aviso dela para este formato.
5. **Sem `APP_MODE=dev` o servidor não sobe.** Assim ninguém roda por engano com Pix falso. No plano 7 isto inverte: o padrão passa a exigir os adaptadores reais.
6. **SOS vale durante toda a corrida** (a caminho, na chegada e andando), não só depois do aviso automático. Se o botão fica sempre visível ou só dentro do aviso (spec, seção 9, itens 4 e 5) é decisão do Levy na tela do app. O servidor não faz ligação: o app liga para o 190; o servidor avisa o contato de emergência (falso até o plano 7) e os administradores.
7. **A compensação do cancelamento tardio não aparece na API.** A política ainda é do Levy (spec, seção 5.3); a API devolve só se há Pix para estornar.
8. **Pix fora do ar:** quando o provedor falha, a API responde 503 e, por 1 minuto, só oferece dinheiro na cotação e recusa novo pedido em Pix.
9. **Limites contra abuso:** 100 pedidos de código por hora por aparelho (alto porque no 4G muita gente divide o mesmo IP), 5 códigos errados de 4 dígitos por corrida em 10 minutos, 30 fotos por hora por motoqueiro.
10. **Trajeto:** a cotação recusa origem e destino a menos de 100 m (não é corrida) ou a mais de 40 km em linha reta (não é corrida de moto na cidade). Ajustáveis em `RideConfig`.
11. **O "chega em X min" da confirmação é uma estimativa sem custo de mapa** (linha reta até a moto livre mais perto, rua 30% mais longa, 25 km/h). O tempo de verdade vem da procura.

## File Structure

Arquivos novos (todos em `server/`, salvo indicação):

| Arquivo | Responsabilidade |
|---|---|
| `app/api/app.py` | monta o FastAPI: rotas, erros, agendador no ciclo de vida |
| `app/api/errors.py` | erros dos serviços → respostas com `code` estável |
| `app/api/deps.py` | quem está chamando e com qual papel |
| `app/api/schemas.py`, `app/api/body.py` | corpos de pedido comuns; leitura de corpo com teto |
| `app/api/views.py` | como a corrida e o estado aparecem para cada lado |
| `app/api/webhook.py` | aviso assinado do provedor e sua conferência |
| `app/api/routes/{auth,passenger,rider,rides,payments,safety,admin,files,ws,dev}.py` | rotas por assunto |
| `app/runtime.py` | `Runtime` e `Unit`: a unidade de trabalho de cada pedido |
| `app/realtime/hub.py` | conexões WebSocket e entrega de avisos de qualquer thread |
| `app/scheduler.py` | varredura, tarefa diária de documentos, limpeza de posições |
| `app/services/safety.py` | parada longa, saída da rota, SOS |
| `app/infra/documents.py`, `app/infra/safety_store.py` | fotos em disco; rastro de segurança no Redis |
| `app/domain/notifier.py`, `app/adapters/fake_notifier.py` | aviso ao contato de emergência (falso até o plano 7) |
| `app/main.py`, `app/cli.py` | ponto de entrada do uvicorn; criar o administrador |
| `migrations/versions/0003_api_e_tempo_real.py`, `0004_alertas_de_seguranca.py` | esquema novo |
| `scripts/smoke_server.py` | sobe o servidor de verdade e confere o caminho completo |
| `../docs/api-v1.md` | contrato da API para os apps, o painel e o simulador |

Arquivos que já existem e mudam: `settings.py`, `domain/config.py`, `domain/rides.py`, `domain/payments.py`, `domain/safety.py`, `db/models.py`, `db/repositories.py`, `db/queries.py`, `db/session.py`, `infra/redis_store.py`, `adapters/fake_otp.py`, `adapters/fake_payments.py`, e os serviços `auth`, `riders`, `quotes`, `ride_requests`, `dispatch`, `trips`, `payments`, `sweeps`.

---

### Task 1: Dependências, configuração e esqueleto da API (erros num formato só)

Instala FastAPI e o uvicorn, acrescenta ao `Settings` o modo, o segredo do aviso do provedor e a pasta das fotos, e cria o esqueleto da API com a tradução de todos os erros dos serviços para respostas HTTP com `code` estável e frase em português. Nenhuma rota de negócio ainda.

**Files:**
- Create: `server/app/api/__init__.py`
- Create: `server/app/api/app.py`
- Create: `server/app/api/errors.py`
- Modify: `server/app/settings.py`
- Modify: `server/pyproject.toml`
- Test: `server/tests/api/__init__.py` (novo)
- Test: `server/tests/api/test_errors.py` (novo)
- Test: `server/tests/test_settings.py` (alterado)

**Interfaces:**
- Consumes: as exceções dos serviços do 2B (`TooManyRequests`, `NotAllowed`, `QuoteExpired`, `OfferGone`, `NotYourRide`, `AlreadyRated`, `InvalidTransition`, `InvalidState`, `RegistrationError`, `DuplicateRegistration`, `CannotGoOnline`, `PaymentProviderError`).
- Produces: `Settings(database_url, redis_url, webhook_secret=None, upload_dir, mode="production")` e `load_settings` lendo `WEBHOOK_SECRET`, `UPLOAD_DIR`, `APP_MODE`; `app.api.errors.ApiError(status, code, message, **extra)`, `error_response(status, code, message, **extra) -> JSONResponse`, `install_error_handlers(app)`; `app.api.app.create_app(runtime=None, *, run_background=False) -> FastAPI`. Corpo de erro sempre `{"error": {"code", "message", ...}}`.

- [ ] **Step 0: Instalar as bibliotecas novas no ambiente do servidor** (antes de tudo)

Run: `.venv/bin/pip install -q "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx2>=2.0"`
Expected: sem erro. `uvicorn[standard]` traz o `websockets`, sem o qual o servidor não aceita WebSocket. `httpx2` é o que o `TestClient` do FastAPI usa (o `httpx` antigo já avisa que está obsoleto).

- [ ] **Step 1: Escrever os testes que falham**

Crie o arquivo vazio `server/tests/api/__init__.py`.

Crie `server/tests/api/test_errors.py`:

````python
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
````

Altere `server/tests/test_settings.py`:

````diff
--- a/server/tests/test_settings.py
+++ b/server/tests/test_settings.py
@@ -39,3 +39,24 @@ def test_url_que_ja_tem_driver_nao_e_alterada(tmp_path):
     env = tmp_path / ".env"
     env.write_text("DATABASE_URL=postgresql+psycopg://u@h/d\nREDIS_URL=redis://h/0\n", encoding="utf-8")
     assert load_settings(env_path=env, environ={}).database_url == "postgresql+psycopg://u@h/d"
+
+
+def test_configuracoes_da_api_tem_padrao_seguro(tmp_path):
+    env = tmp_path / ".env"
+    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n", encoding="utf-8")
+    settings = load_settings(env_path=env, environ={})
+    assert settings.mode == "production"          # sem APP_MODE=dev não liga os adaptadores falsos
+    assert settings.webhook_secret is None
+    assert settings.upload_dir.name == "uploads" and settings.upload_dir.parent.name == "var"
+
+
+def test_le_modo_segredo_do_webhook_e_pasta_de_documentos(tmp_path):
+    env = tmp_path / ".env"
+    env.write_text(
+        "DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n"
+        "APP_MODE=dev\nWEBHOOK_SECRET=segredo\nUPLOAD_DIR=/dados/docs\n",
+        encoding="utf-8",
+    )
+    settings = load_settings(env_path=env, environ={})
+    assert (settings.mode, settings.webhook_secret) == ("dev", "segredo")
+    assert str(settings.upload_dir) == "/dados/docs"
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_errors.py tests/test_settings.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.api.app'`.

- [ ] **Step 3: Implementar**

Crie o arquivo vazio `server/app/api/__init__.py`.

Crie `server/app/api/app.py`:

````python
"""Montagem da aplicação FastAPI. As rotas ficam em `app/api/routes/`; a lógica, nos serviços."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.errors import install_error_handlers


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
    return app
````

Crie `server/app/api/errors.py`:

````python
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
from app.domain.rides import InvalidTransition
from app.services.auth import TooManyRequests
from app.services.dispatch import OfferGone
from app.services.quotes import NotAllowed, QuoteExpired
from app.services.riders import CannotGoOnline, DuplicateRegistration, InvalidState, RegistrationError
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
    InvalidTransition: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual da corrida."),
    InvalidState: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual do cadastro."),
    RegistrationError: _Rule(422, "invalid"),
    ValueError: _Rule(422, "invalid"),
    PaymentProviderError: _Rule(503, "payment_unavailable", "O Pix está instável agora. Tente de novo em instantes."),
}

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
    app.add_exception_handler(DuplicateRegistration, _duplicate_registration)
    app.add_exception_handler(LookupError, _not_found)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _internal)
````

Altere `server/app/settings.py`:

````diff
--- a/server/app/settings.py
+++ b/server/app/settings.py
@@ -9,13 +9,18 @@ from collections.abc import Mapping
 from dataclasses import dataclass
 from pathlib import Path
 
-_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
+_SERVER_DIR = Path(__file__).resolve().parents[1]
+_DEFAULT_ENV_PATH = _SERVER_DIR / ".env"
+_DEFAULT_UPLOAD_DIR = _SERVER_DIR / "var" / "uploads"
 
 
 @dataclass(frozen=True)
 class Settings:
     database_url: str
     redis_url: str
+    webhook_secret: str | None = None       # assina os avisos do provedor de pagamento (HMAC)
+    upload_dir: Path = _DEFAULT_UPLOAD_DIR  # onde ficam as fotos dos documentos (fora do git)
+    mode: str = "production"                # "dev" liga os adaptadores falsos, os únicos que existem até o plano 7
 
 
 def parse_env_file(path: Path) -> dict[str, str]:
@@ -52,4 +57,14 @@ def load_settings(
             raise RuntimeError(f"falta a configuração {key} (defina no ambiente ou em server/.env)")
         return value
 
-    return Settings(database_url=_with_driver(get("DATABASE_URL")), redis_url=get("REDIS_URL"))
+    def optional(key: str) -> str | None:
+        return env.get(key) or file_values.get(key) or None
+
+    upload_dir = optional("UPLOAD_DIR")
+    return Settings(
+        database_url=_with_driver(get("DATABASE_URL")),
+        redis_url=get("REDIS_URL"),
+        webhook_secret=optional("WEBHOOK_SECRET"),
+        upload_dir=Path(upload_dir) if upload_dir else _DEFAULT_UPLOAD_DIR,
+        mode=optional("APP_MODE") or "production",
+    )
````

Altere `server/pyproject.toml`:

````diff
--- a/server/pyproject.toml
+++ b/server/pyproject.toml
@@ -9,10 +9,12 @@ dependencies = [
     "alembic>=1.13",
     "redis>=5.0",
     "tzdata>=2024.1",
+    "fastapi>=0.115",
+    "uvicorn[standard]>=0.30",
 ]
 
 [project.optional-dependencies]
-dev = ["pytest>=8"]
+dev = ["pytest>=8", "httpx2>=2.0"]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_errors.py tests/test_settings.py`
Expected: `28 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `404 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): esqueleto da API com tradução dos erros dos serviços" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 2: Esquema novo: código do Pix, rota da corrida, contato de emergência, chave e índices (migração 0003)

Uma migração só com tudo que as tarefas seguintes precisam do banco: texto do Pix (`br_code`) para o app desenhar o QR, a rota da corrida (para o aviso de saída da rota), o tempo de chegada guardado na oferta (para o app reconectar), o contato de emergência do passageiro, a chave estrangeira que faltava em `rides.current_charge_id`, índices de consulta e o índice único de uma corrida aberta por passageiro. Fecha os itens do roteiro sobre CHECKs, chave e `compare_metadata`.

**Files:**
- Modify: `server/app/adapters/fake_payments.py`
- Modify: `server/app/db/models.py`
- Modify: `server/app/db/repositories.py`
- Modify: `server/app/domain/config.py`
- Modify: `server/app/domain/payments.py`
- Modify: `server/app/domain/rides.py`
- Create: `server/migrations/versions/0003_api_e_tempo_real.py`
- Test: `server/tests/adapters/__init__.py` (novo)
- Test: `server/tests/adapters/test_fake_payments.py` (novo)
- Test: `server/tests/db/test_repositories.py` (alterado)
- Test: `server/tests/db/test_repositories_api.py` (novo)
- Test: `server/tests/db/test_schema_api.py` (novo)
- Test: `server/tests/db/test_schema_corrida.py` (alterado)
- Test: `server/tests/domain/test_config_api.py` (novo)
- Test: `server/tests/services/test_dia_de_trabalho.py` (alterado)
- Test: `server/tests/services/test_payment_service.py` (alterado)

**Interfaces:**
- Consumes: `PixCharge`, `RideDetails`, `FakePaymentProvider`, os repositórios do 2A/2B.
- Produces: `PixCharge.br_code: str = ""` (o provedor falso gera `fake-pix|<id>|<centavos>`); `repo.RideDetails.route: tuple[tuple[float, float], ...] = ()`; `repo.EmergencyContact(name, phone)`, `repo.get_emergency_contact(session, passenger_id) -> EmergencyContact | None`, `repo.set_emergency_contact(session, passenger_id, name, phone)`; `app.domain.rides.WrongPin(ValueError)`; `RideConfig.min_trip_m = 100` e `max_trip_m = 40_000`; `SafetyConfig.alert_cooldown_s = 600` e `max_samples = 120`; colunas `quotes.route`, `rides.route`, `pix_charges.br_code`, `ride_offers.eta_seconds`, `passenger_profiles.emergency_name/emergency_phone`; no banco, a chave `rides_current_charge_fk`, os índices `ix_rides_state`, `ix_rides_passenger_state`, `ix_rides_rider_state`, `ix_ride_offers_ride_id` e o índice único `ride_one_open_per_passenger`.

- [ ] **Step 1: Escrever os testes que falham**

Crie o arquivo vazio `server/tests/adapters/__init__.py`.

Crie `server/tests/adapters/test_fake_payments.py`:

````python
from app.adapters.fake_payments import FakePaymentProvider
from app.domain.payments import compute_split


def test_cada_cobranca_falsa_tem_codigo_proprio_com_o_valor():
    provider = FakePaymentProvider()
    a = provider.create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
    b = provider.create_pix_charge("ride-2", "r1", 900, compute_split(900, 100, 0))
    assert a.br_code != b.br_code
    assert a.br_code == f"fake-pix|{a.charge_id}|700"
````

Altere `server/tests/db/test_repositories.py`:

````diff
--- a/server/tests/db/test_repositories.py
+++ b/server/tests/db/test_repositories.py
@@ -61,9 +61,11 @@ def test_cobranca_atual_da_corrida(session):
     add_passenger(session)
     add_rider(session)
     add_accepted_ride(session)
+    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
+    repo.add_charge(session, charge)
     assert repo.get_current_charge_id(session, "ride-1") is None
-    repo.set_current_charge(session, "ride-1", "ch-1")
-    assert repo.get_current_charge_id(session, "ride-1") == "ch-1"
+    repo.set_current_charge(session, "ride-1", charge.charge_id)
+    assert repo.get_current_charge_id(session, "ride-1") == charge.charge_id
     repo.set_current_charge(session, "ride-1", None)
     assert repo.get_current_charge_id(session, "ride-1") is None
 
````

Crie `server/tests/db/test_repositories_api.py`:

````python
from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.domain.geo import GeoPoint
from app.domain.payments import compute_split
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider


def test_codigo_do_pix_vai_e_volta_com_a_cobranca(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    charge = FakePaymentProvider().create_pix_charge("ride-1", "r1", 700, compute_split(700, 100, 0))
    assert charge.br_code.startswith("fake-pix|")
    repo.add_charge(session, charge)
    session.expire_all()
    assert repo.get_charge(session, charge.charge_id).br_code == charge.br_code


def test_detalhes_da_corrida_guardam_a_rota(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    rota = ((-12.9644, -39.2597), (-12.9600, -39.2500))
    repo.set_ride_details(
        session, "ride-1",
        repo.RideDetails(GeoPoint(-12.9644, -39.2597), GeoPoint(-12.96, -39.25), "A", "B", 1500, 1.0, "normal", route=rota),
    )
    session.expire_all()
    assert repo.get_ride_details(session, "ride-1").route == rota


def test_detalhes_sem_rota_voltam_com_rota_vazia(session):
    add_passenger(session)
    add_rider(session)
    add_accepted_ride(session)
    repo.set_ride_details(
        session, "ride-1",
        repo.RideDetails(GeoPoint(-12.9644, -39.2597), GeoPoint(-12.96, -39.25), "A", "B", 1500, 1.0, "normal"),
    )
    session.expire_all()
    assert repo.get_ride_details(session, "ride-1").route == ()


def test_contato_de_emergencia_vai_e_volta(session):
    add_passenger(session)
    assert repo.get_emergency_contact(session, "p1") is None
    repo.set_emergency_contact(session, "p1", "Maria", "+5575988887777")
    session.expire_all()
    assert repo.get_emergency_contact(session, "p1") == repo.EmergencyContact("Maria", "+5575988887777")
    repo.set_emergency_contact(session, "p1", "João", "+5575911112222")
    assert repo.get_emergency_contact(session, "p1").name == "João"
````

Crie `server/tests/db/test_schema_api.py`:

````python
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import Base, PassengerProfileRow, PixChargeRow, QuoteRow, RideOfferRow, RideRow
from tests.helpers_db import add_passenger, add_rider


def _ride(ride_id: str, passenger_id: str = "p1", state: str = "searching", **extra) -> RideRow:
    return RideRow(
        id=ride_id, passenger_id=passenger_id, price_cents=700, payment_method="pix", pin="4821", state=state, **extra
    )


def test_modelos_e_migracoes_dizem_a_mesma_coisa(db_engine):
    # Itens do roteiro (revisão do 2A): o Alembic compara os modelos com o banco migrado e não acha diferença.
    # A tabela `spatial_ref_sys` é do PostGIS e aparece pelo search_path; não é nossa.
    def so_nossas(obj, name, type_, reflected, compare_to):
        return not (type_ == "table" and name == "spatial_ref_sys")

    with db_engine.connect() as conn:
        contexto = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True, "include_object": so_nossas}
        )
        assert compare_metadata(contexto, Base.metadata) == []


def test_cobranca_guarda_o_codigo_do_pix_e_comeca_vazio(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1"))
    session.flush()
    session.add(
        PixChargeRow(
            charge_id="ch-1", ride_id="ride-1", rider_id="r1", amount_cents=700, rider_cents=600,
            company_cents=100, debt_paid_cents=0,
        )
    )
    session.flush()
    assert session.get(PixChargeRow, "ch-1").br_code == ""
    session.get(PixChargeRow, "ch-1").br_code = "00020126..."
    session.flush()
    session.expire_all()
    assert session.get(PixChargeRow, "ch-1").br_code == "00020126..."


def test_corrida_e_cotacao_guardam_a_rota_e_a_oferta_guarda_o_tempo_de_chegada(session):
    add_passenger(session)
    add_rider(session)
    session.add(_ride("ride-1", route=[[-12.96, -39.26], [-12.95, -39.25]]))
    session.add(
        QuoteRow(
            id="q-1", passenger_id="p1", pickup_lat=0, pickup_lng=0, dest_lat=1, dest_lng=1, distance_m=100,
            duration_s=30, price_cents=500, factor=1.0, reason="x", created_at=1.0, expires_at=2.0,
            route=[[0, 0], [1, 1]],
        )
    )
    session.flush()
    session.add(
        RideOfferRow(ride_id="ride-1", rider_id="r1", created_at=1.0, expires_at=16.0, eta_seconds=95)
    )
    session.flush()
    session.expire_all()
    assert session.get(RideRow, "ride-1").route == [[-12.96, -39.26], [-12.95, -39.25]]
    assert session.get(QuoteRow, "q-1").route == [[0, 0], [1, 1]]
    assert session.get(RideRow, "ride-1").pickup_lat is None      # corrida sem rota continua válida
    assert session.query(RideOfferRow).one().eta_seconds == 95


def test_passageiro_guarda_um_contato_de_emergencia(session):
    add_passenger(session)
    perfil = session.get(PassengerProfileRow, "p1")
    assert (perfil.emergency_name, perfil.emergency_phone) == (None, None)
    perfil.emergency_name, perfil.emergency_phone = "Maria", "+5575988887777"
    session.flush()
    session.expire_all()
    assert session.get(PassengerProfileRow, "p1").emergency_phone == "+5575988887777"


def test_corrida_nao_aponta_para_cobranca_que_nao_existe(session):
    add_passenger(session)
    session.add(_ride("ride-1", current_charge_id="ch-fantasma"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_so_uma_corrida_aberta_por_passageiro(session):
    add_passenger(session)
    session.add(_ride("ride-1", state="searching"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(_ride("ride-2", state="accepted"))
            session.flush()


@pytest.mark.parametrize("estado", ["completed", "cancelled", "no_rider"])
def test_corrida_terminada_nao_conta_como_aberta(session, estado):
    add_passenger(session)
    session.add(_ride("ride-1", state=estado))
    session.add(_ride("ride-2", state="searching"))
    session.add(_ride("ride-3", state=estado))
    session.flush()


def test_indices_de_consulta_existem(session):
    nomes = set(
        session.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")).scalars()
    )
    assert {
        "ix_rides_state", "ix_rides_passenger_state", "ix_rides_rider_state", "ix_ride_offers_ride_id",
        "ride_one_open_per_passenger",
    } <= nomes
````

Altere `server/tests/db/test_schema_corrida.py`:

````diff
--- a/server/tests/db/test_schema_corrida.py
+++ b/server/tests/db/test_schema_corrida.py
@@ -35,8 +35,9 @@ def test_so_uma_oferta_pendente_por_corrida(session):
 
 def test_so_uma_oferta_pendente_por_motoqueiro(session):
     add_passenger(session)
+    add_passenger(session, "p2", "+5575900000010")
     add_rider(session)
-    session.add_all([_ride("ride-1"), _ride("ride-2")])
+    session.add_all([_ride("ride-1"), _ride("ride-2", "p2")])
     session.flush()
     session.add(_offer("ride-1", "r1"))
     session.flush()
````

Crie `server/tests/domain/test_config_api.py`:

````python
import pytest

from app.domain.config import RideConfig, SafetyConfig
from app.domain.rides import Ride, RideState, WrongPin, accept, confirm_helmet, mark_arrived, start_ride, start_search
from app.domain.types import PaymentMethod


def test_limites_novos_tem_padrao():
    assert (RideConfig().min_trip_m, RideConfig().max_trip_m) == (100, 40_000)
    assert (SafetyConfig().alert_cooldown_s, SafetyConfig().max_samples) == (600, 120)


def test_codigo_errado_e_um_erro_proprio_mas_continua_sendo_value_error():
    ride = Ride("ride-1", "p1", 700, PaymentMethod.CASH, pin="4821")
    start_search(ride, 0)
    accept(ride, "r1", 1, rider_busy=False)
    mark_arrived(ride, 2)
    confirm_helmet(ride)
    with pytest.raises(WrongPin) as erro:
        start_ride(ride, "0000")
    assert isinstance(erro.value, ValueError)
    assert ride.state is RideState.ARRIVED
````

Altere `server/tests/services/test_dia_de_trabalho.py`:

````diff
--- a/server/tests/services/test_dia_de_trabalho.py
+++ b/server/tests/services/test_dia_de_trabalho.py
@@ -14,6 +14,8 @@ def test_dia_de_trabalho_com_dinheiro_pix_e_estorno_fecha_as_contas(session):
     provider = FakePaymentProvider()
     service = PaymentService(provider)
     add_passenger(session)
+    add_passenger(session, "p2", "+5575900000010")     # uma corrida aberta por passageiro
+    add_passenger(session, "p3", "+5575900000011")
     add_rider(session)
 
     # 1) uma corrida em dinheiro já concluída: a taxa vira dívida do motoqueiro
@@ -23,7 +25,7 @@ def test_dia_de_trabalho_com_dinheiro_pix_e_estorno_fecha_as_contas(session):
     assert repo.get_rider_account(session, "r1").cash_debt_cents == 100
 
     # 2) uma corrida Pix de R$ 7,00: a dívida é abatida quando o Pix é pago
-    add_accepted_ride(session, ride_id="ride-2", price=700)
+    add_accepted_ride(session, ride_id="ride-2", passenger_id="p2", price=700)
     charge2 = service.start_pix_charge(session, "ride-2", FEE)
     assert repo.get_rider_account(session, "r1").cash_debt_cents == 100  # ainda não abateu
     assert service.on_provider_event(session, provider.mark_paid(charge2.charge_id)) == "applied"
@@ -33,7 +35,7 @@ def test_dia_de_trabalho_com_dinheiro_pix_e_estorno_fecha_as_contas(session):
     assert (acc.cash_debt_cents, acc.debt_reserved_cents, acc.completed_rides) == (0, 0, 2)
 
     # 3) uma corrida Pix de R$ 6,00, paga e depois cancelada: o dinheiro volta
-    add_accepted_ride(session, ride_id="ride-3", price=600)
+    add_accepted_ride(session, ride_id="ride-3", passenger_id="p3", price=600)
     charge3 = service.start_pix_charge(session, "ride-3", FEE)
     service.on_provider_event(session, provider.mark_paid(charge3.charge_id))
     assert service.cancel_ride(session, "ride-3", now=20) == CancelResult(0, True)
````

Altere `server/tests/services/test_payment_service.py`:

````diff
--- a/server/tests/services/test_payment_service.py
+++ b/server/tests/services/test_payment_service.py
@@ -68,7 +68,8 @@ def test_so_cobra_pix_de_corrida_aceita_por_um_motoqueiro(session, service):
     mundo(session, method=PaymentMethod.CASH)
     with pytest.raises(InvalidTransition, match="Pix"):
         service.start_pix_charge(session, "ride-1", FEE)
-    ride = Ride("ride-2", "p1", 700, PaymentMethod.PIX, pin="4821")
+    add_passenger(session, "p2", "+5575900000010")    # uma corrida aberta por passageiro
+    ride = Ride("ride-2", "p2", 700, PaymentMethod.PIX, pin="4821")
     repo.add_ride(session, ride)
     with pytest.raises(InvalidTransition):
         service.start_pix_charge(session, "ride-2", FEE)
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q \
  tests/adapters/test_fake_payments.py \
  tests/db/test_repositories.py \
  tests/db/test_repositories_api.py \
  tests/db/test_schema_api.py \
  tests/db/test_schema_corrida.py \
  tests/domain/test_config_api.py \
  tests/services/test_dia_de_trabalho.py \
  tests/services/test_payment_service.py`
Expected: erro ao carregar os testes — `ImportError: cannot import name 'WrongPin' from 'app.domain.rides'`.

- [ ] **Step 3: Implementar**

Altere `server/app/adapters/fake_payments.py`:

````diff
--- a/server/app/adapters/fake_payments.py
+++ b/server/app/adapters/fake_payments.py
@@ -22,6 +22,7 @@ class FakePaymentProvider:
             amount_cents=amount_cents,
             split=split,
             purpose=purpose,
+            br_code=f"fake-pix|ch-{self._counter}|{amount_cents}",
         )
         self.charges[charge.charge_id] = charge
         return charge
````

Altere `server/app/db/models.py`:

````diff
--- a/server/app/db/models.py
+++ b/server/app/db/models.py
@@ -79,11 +79,22 @@ class PassengerProfileRow(Base):
 
     user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
     unpaid_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
+    emergency_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
+    emergency_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
 
 
 class RideRow(Base):
     __tablename__ = "rides"
-    __table_args__ = (CheckConstraint("price_cents > 0", name="ride_price_positive"),)
+    __table_args__ = (
+        CheckConstraint("price_cents > 0", name="ride_price_positive"),
+        Index("ix_rides_state", "state"),
+        Index("ix_rides_passenger_state", "passenger_id", "state"),
+        Index("ix_rides_rider_state", "rider_id", "state"),
+        Index(
+            "ride_one_open_per_passenger", "passenger_id", unique=True,
+            postgresql_where=text("state NOT IN ('completed','cancelled','no_rider')"),
+        ),
+    )
 
     id: Mapped[str] = mapped_column(String(40), primary_key=True)
     passenger_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
@@ -101,7 +112,9 @@ class RideRow(Base):
     arrived_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
     end_payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
     non_payment_reported: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
-    current_charge_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
+    current_charge_id: Mapped[str | None] = mapped_column(
+        String(40), ForeignKey("pix_charges.charge_id", use_alter=True, name="rides_current_charge_fk"), nullable=True
+    )
     pickup_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
     pickup_lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
     dest_lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
@@ -111,6 +124,7 @@ class RideRow(Base):
     distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
     price_factor: Mapped[float | None] = mapped_column(Float(53), nullable=True)
     price_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
+    route: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [[lat, lng], ...] do preço mostrado
     fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
     completed_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
     created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
@@ -135,6 +149,7 @@ class PixChargeRow(Base):
     paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
     refunded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
     debt_state: Mapped[str] = mapped_column(String(12), default="reserved", server_default="reserved")
+    br_code: Mapped[str] = mapped_column(Text, default="", server_default="")
     created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
 
 
@@ -210,6 +225,7 @@ class QuoteRow(Base):
     price_cents: Mapped[int] = mapped_column(Integer)
     factor: Mapped[float] = mapped_column(Float(53))
     reason: Mapped[str] = mapped_column(String(80))
+    route: Mapped[list | None] = mapped_column(JSONB, nullable=True)
     created_at: Mapped[float] = mapped_column(Float(53))
     expires_at: Mapped[float] = mapped_column(Float(53))
     used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
@@ -221,6 +237,7 @@ class RideOfferRow(Base):
         CheckConstraint("status IN ('pending','accepted','declined','expired')", name="offer_status_valid"),
         Index("offer_one_pending_per_ride", "ride_id", unique=True, postgresql_where=text("status = 'pending'")),
         Index("offer_one_pending_per_rider", "rider_id", unique=True, postgresql_where=text("status = 'pending'")),
+        Index("ix_ride_offers_ride_id", "ride_id"),
     )
 
     id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
@@ -228,6 +245,7 @@ class RideOfferRow(Base):
     rider_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
     status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
     will_queue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
+    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
     created_at: Mapped[float] = mapped_column(Float(53))
     expires_at: Mapped[float] = mapped_column(Float(53))
 
````

Altere `server/app/db/repositories.py`:

````diff
--- a/server/app/db/repositories.py
+++ b/server/app/db/repositories.py
@@ -110,6 +110,29 @@ def save_passenger_account(session: Session, acc: PassengerAccount) -> None:
     session.flush()
 
 
+@dataclass(frozen=True)
+class EmergencyContact:
+    name: str
+    phone: str
+
+
+def get_emergency_contact(session: Session, passenger_id: str) -> EmergencyContact | None:
+    row = session.get(PassengerProfileRow, passenger_id)
+    if row is None:
+        raise LookupError(f"passageiro {passenger_id} não encontrado")
+    if not row.emergency_phone:
+        return None
+    return EmergencyContact(row.emergency_name or "", row.emergency_phone)
+
+
+def set_emergency_contact(session: Session, passenger_id: str, name: str, phone: str) -> None:
+    row = session.get(PassengerProfileRow, passenger_id)
+    if row is None:
+        raise LookupError(f"passageiro {passenger_id} não encontrado")
+    row.emergency_name, row.emergency_phone = name, phone
+    session.flush()
+
+
 # --- corridas ----------------------------------------------------------------
 
 
@@ -212,6 +235,7 @@ def _charge_to_domain(row: PixChargeRow) -> PixCharge:
         refunded=row.refunded,
         debt_state=DebtState(row.debt_state),
         purpose=row.purpose,
+        br_code=row.br_code,
     )
 
 
@@ -226,6 +250,7 @@ def _apply_charge(row: PixChargeRow, charge: PixCharge) -> None:
     row.refunded = charge.refunded
     row.debt_state = charge.debt_state.value
     row.purpose = charge.purpose
+    row.br_code = charge.br_code
 
 
 def add_charge(session: Session, charge: PixCharge) -> None:
@@ -275,6 +300,7 @@ class RideDetails:
     distance_m: int
     price_factor: float
     price_reason: str
+    route: tuple[tuple[float, float], ...] = ()     # pontos (lat, lng) do trajeto, vindos do mapa na hora do preço
 
 
 def set_ride_details(session: Session, ride_id: str, details: RideDetails) -> None:
@@ -285,6 +311,7 @@ def set_ride_details(session: Session, ride_id: str, details: RideDetails) -> No
     row.dest_lat, row.dest_lng = details.destination.lat, details.destination.lng
     row.pickup_text, row.dest_text = details.pickup_text, details.destination_text
     row.distance_m, row.price_factor, row.price_reason = details.distance_m, details.price_factor, details.price_reason
+    row.route = [list(point) for point in details.route] or None
     session.flush()
 
 
@@ -302,6 +329,7 @@ def get_ride_details(session: Session, ride_id: str) -> RideDetails:
         distance_m=row.distance_m or 0,
         price_factor=row.price_factor if row.price_factor is not None else 1.0,
         price_reason=row.price_reason or "",
+        route=tuple((float(lat), float(lng)) for lat, lng in (row.route or ())),
     )
 
 
````

Altere `server/app/domain/config.py`:

````diff
--- a/server/app/domain/config.py
+++ b/server/app/domain/config.py
@@ -48,6 +48,8 @@ class RideConfig:
     search_give_up_s: int = 120
     cash_pay_wait_s: int = 300      # espera pelo pagamento do fim da corrida em dinheiro
     quote_ttl_s: int = 300          # validade do preço mostrado antes do pedido
+    min_trip_m: int = 100           # origem e destino mais perto que isso não é corrida
+    max_trip_m: int = 40_000        # em linha reta; mais longe que isso não é corrida de moto na cidade
 
 
 @dataclass(frozen=True)
@@ -69,6 +71,8 @@ class SafetyConfig:
     max_plausible_speed_kmh: float = 140.0
     reanchor_after_rejects: int = 3
     mock_location_jumps: int = 2
+    alert_cooldown_s: int = 600     # depois de um aviso, o mesmo tipo de aviso não repete nesse tempo
+    max_samples: int = 120          # posições guardadas por corrida (cerca de 8 minutos a cada 4 s)
 
 
 @dataclass(frozen=True)
````

Altere `server/app/domain/payments.py`:

````diff
--- a/server/app/domain/payments.py
+++ b/server/app/domain/payments.py
@@ -124,6 +124,7 @@ class PixCharge:
     refunded: bool = False
     debt_state: DebtState = DebtState.RESERVED
     purpose: str = "ride"   # "ride" (Pix antes da corrida), "end" (QR do fim em dinheiro) ou "entry" (entrada de R$ 50)
+    br_code: str = ""       # texto do Pix "copia e cola"; o app desenha o QR a partir dele
 
 
 class PaymentProviderError(Exception):
````

Altere `server/app/domain/rides.py`:

````diff
--- a/server/app/domain/rides.py
+++ b/server/app/domain/rides.py
@@ -26,6 +26,10 @@ class InvalidTransition(Exception):
     """A ação não é permitida no estado atual da corrida."""
 
 
+class WrongPin(ValueError):
+    """O código de 4 dígitos informado pelo motoqueiro não é o da corrida."""
+
+
 @dataclass
 class Ride:
     ride_id: str
@@ -169,7 +173,7 @@ def start_ride(ride: Ride, pin: str) -> None:
     if ride.payment_method is PaymentMethod.PIX and not ride.pix_paid:
         raise InvalidTransition("o Pix ainda não foi pago")
     if pin != ride.pin:
-        raise ValueError("código errado")
+        raise WrongPin("código errado")
     ride.state = RideState.IN_PROGRESS
 
 
````

Crie `server/migrations/versions/0003_api_e_tempo_real.py`:

````python
"""api e tempo real: código do Pix, rota da corrida, contato de emergência, chave e índices

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_ABERTA = "state NOT IN ('completed','cancelled','no_rider')"


def upgrade() -> None:
    op.add_column("pix_charges", sa.Column("br_code", sa.Text(), nullable=False, server_default=""))
    op.add_column("quotes", sa.Column("route", postgresql.JSONB(), nullable=True))
    op.add_column("rides", sa.Column("route", postgresql.JSONB(), nullable=True))
    op.add_column("ride_offers", sa.Column("eta_seconds", sa.Integer(), nullable=True))
    op.add_column("passenger_profiles", sa.Column("emergency_name", sa.String(120), nullable=True))
    op.add_column("passenger_profiles", sa.Column("emergency_phone", sa.String(20), nullable=True))

    op.create_foreign_key("rides_current_charge_fk", "rides", "pix_charges", ["current_charge_id"], ["charge_id"])
    op.create_index("ix_rides_state", "rides", ["state"])
    op.create_index("ix_rides_passenger_state", "rides", ["passenger_id", "state"])
    op.create_index("ix_rides_rider_state", "rides", ["rider_id", "state"])
    op.create_index("ix_ride_offers_ride_id", "ride_offers", ["ride_id"])
    op.create_index(
        "ride_one_open_per_passenger", "rides", ["passenger_id"], unique=True, postgresql_where=sa.text(_ABERTA)
    )


def downgrade() -> None:
    op.drop_index("ride_one_open_per_passenger", table_name="rides")
    op.drop_index("ix_ride_offers_ride_id", table_name="ride_offers")
    op.drop_index("ix_rides_rider_state", table_name="rides")
    op.drop_index("ix_rides_passenger_state", table_name="rides")
    op.drop_index("ix_rides_state", table_name="rides")
    op.drop_constraint("rides_current_charge_fk", "rides", type_="foreignkey")
    op.drop_column("passenger_profiles", "emergency_phone")
    op.drop_column("passenger_profiles", "emergency_name")
    op.drop_column("ride_offers", "eta_seconds")
    op.drop_column("rides", "route")
    op.drop_column("quotes", "route")
    op.drop_column("pix_charges", "br_code")
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q \
  tests/adapters/test_fake_payments.py \
  tests/db/test_repositories.py \
  tests/db/test_repositories_api.py \
  tests/db/test_schema_api.py \
  tests/db/test_schema_corrida.py \
  tests/domain/test_config_api.py \
  tests/services/test_dia_de_trabalho.py \
  tests/services/test_payment_service.py`
Expected: `54 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `421 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Aplicar a migração no banco de desenvolvimento e conferir**

Run: `.venv/bin/alembic upgrade head`
Expected: termina com `Running upgrade 0002 -> 0003`. Se falhar por `ride_one_open_per_passenger` (duas corridas abertas do mesmo passageiro no banco de desenvolvimento), pare e investigue as linhas antes de apagar qualquer coisa.

Run: `.venv/bin/alembic current`
Expected: `0003 (head)`

- [ ] **Step 7: Commit**

```bash
cd .. && git add server && git commit -m "feat(db): migração 0003 com código do Pix, rota, contato de emergência, chave e índices" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 3: Hub de tempo real e lojas auxiliares (limite de tentativas, saúde do Pix, marcas de tarefas, limpeza de posições)

As peças de apoio, cada uma com versão em memória (testes) e versão Redis (servidor): o hub que entrega avisos às conexões WebSocket de qualquer thread, o limite de tentativas, a marca de "Pix fora do ar", as marcas das tarefas diárias e a limpeza das posições que somem.

**Files:**
- Modify: `server/app/infra/redis_store.py`
- Create: `server/app/realtime/__init__.py`
- Create: `server/app/realtime/hub.py`
- Test: `server/tests/infra/test_stores_api.py` (novo)
- Test: `server/tests/realtime/__init__.py` (novo)
- Test: `server/tests/realtime/test_hub.py` (novo)

**Interfaces:**
- Consumes: `app.services.events.Event`, `PositionStore` e `redis_client` (fixture do 2A).
- Produces: `app.realtime.hub`: `to_message(event, now) -> dict`, `Connection(user_id, loop, max_queue=100)` (`deliver(message)`, `queue`, `overflowed`), `Hub` (`add`, `remove`, `publish(user_id, message) -> int`, `publish_events(events, now)`, `count()`). Em `app.infra.redis_store`: `PositionStore.prune(now, max_age_s) -> int`; `RateLimiter.hit(key, limit, window_s, now) -> bool` (`InMemoryRateLimiter`, `RedisRateLimiter`); `PixHealth.mark_down(now, for_s)` e `is_down(now)` (`InMemoryPixHealth`, `RedisPixHealth`); `JobMarks.get(name)` e `set(name, value)` (`InMemoryJobMarks`, `RedisJobMarks`).

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/infra/test_stores_api.py`:

````python
import pytest

from app.infra.redis_store import (
    InMemoryJobMarks,
    InMemoryPixHealth,
    InMemoryPositionStore,
    InMemoryRateLimiter,
    RedisJobMarks,
    RedisPixHealth,
    RedisPositionStore,
    RedisRateLimiter,
)
from tests.helpers import pt


@pytest.fixture(params=["memoria", "redis"])
def limiter(request, redis_client):
    return InMemoryRateLimiter() if request.param == "memoria" else RedisRateLimiter(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def health(request, redis_client):
    return InMemoryPixHealth() if request.param == "memoria" else RedisPixHealth(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def marks(request, redis_client):
    return InMemoryJobMarks() if request.param == "memoria" else RedisJobMarks(redis_client)


@pytest.fixture(params=["memoria", "redis"])
def positions(request, redis_client):
    return InMemoryPositionStore() if request.param == "memoria" else RedisPositionStore(redis_client)


def test_limitador_deixa_passar_ate_o_limite_e_zera_na_janela_seguinte(limiter):
    for _ in range(3):
        assert limiter.hit("pin:ride-1", 3, 600, now=1000.0) is True
    assert limiter.hit("pin:ride-1", 3, 600, now=1001.0) is False
    assert limiter.hit("pin:ride-2", 3, 600, now=1001.0) is True        # outra chave tem a sua contagem
    assert limiter.hit("pin:ride-1", 3, 600, now=1600.0) is True        # janela seguinte


def test_pix_fora_do_ar_volta_sozinho_depois_do_prazo(health):
    assert health.is_down(100.0) is False
    health.mark_down(100.0, for_s=60.0)
    assert health.is_down(120.0) is True
    assert health.is_down(161.0) is False


def test_marca_de_tarefa_guarda_o_ultimo_valor(marks):
    assert marks.get("docs") is None
    marks.set("docs", "2026-10-18")
    assert marks.get("docs") == "2026-10-18"
    marks.set("docs", "2026-10-19")
    assert marks.get("docs") == "2026-10-19"


def test_limpeza_tira_so_quem_sumiu(positions):
    positions.update("velho", pt(0, 0), now=100.0)
    positions.update("novo", pt(10, 0), now=900.0)
    assert positions.prune(now=1000.0, max_age_s=300.0) == 1
    assert positions.get("velho") is None
    assert positions.get("novo") is not None
    assert positions.nearby(pt(0, 0), 1000.0, now=1000.0, max_age_s=300.0)[0][0] == "novo"
    assert positions.prune(now=1000.0, max_age_s=300.0) == 0
````

Crie o arquivo vazio `server/tests/realtime/__init__.py`.

Crie `server/tests/realtime/test_hub.py`:

````python
import asyncio

from app.realtime.hub import Connection, Hub, to_message
from app.services.events import Event


def test_mensagem_tem_tipo_dados_e_hora():
    assert to_message(Event("u1", "offer", {"ride_id": "ride-1"}), 12.5) == {
        "type": "offer", "data": {"ride_id": "ride-1"}, "at": 12.5,
    }


def test_publicar_de_outra_thread_chega_na_fila_da_conexao():
    async def main():
        hub = Hub()
        conn = Connection("u1", asyncio.get_running_loop())
        hub.add(conn)
        entregues = await asyncio.to_thread(hub.publish, "u1", {"type": "a"})   # como um pedido HTTP síncrono
        return entregues, await asyncio.wait_for(conn.queue.get(), 1)

    assert asyncio.run(main()) == (1, {"type": "a"})


def test_quem_nao_esta_conectado_nao_recebe_nada_e_nao_da_erro():
    assert Hub().publish("ninguem", {"type": "a"}) == 0


def test_duas_telas_do_mesmo_usuario_recebem_e_a_removida_nao():
    async def main():
        hub = Hub()
        loop = asyncio.get_running_loop()
        a, b = Connection("u1", loop), Connection("u1", loop)
        hub.add(a)
        hub.add(b)
        hub.remove(a)
        entregues = hub.publish("u1", {"type": "x"})
        await asyncio.sleep(0)
        return entregues, a.queue.qsize(), b.queue.qsize()

    assert asyncio.run(main()) == (1, 0, 1)


def test_publicar_varios_avisos_respeita_o_dono_de_cada_um():
    async def main():
        hub = Hub()
        loop = asyncio.get_running_loop()
        pax, rider = Connection("p1", loop), Connection("r1", loop)
        hub.add(pax)
        hub.add(rider)
        hub.publish_events([Event("p1", "rider_accepted", {}), Event("r1", "ride_assigned", {}), Event("zz", "x")], 5.0)
        await asyncio.sleep(0)
        return (await pax.queue.get())["type"], (await rider.queue.get())["type"]

    assert asyncio.run(main()) == ("rider_accepted", "ride_assigned")


def test_fila_cheia_marca_a_conexao_em_vez_de_perder_aviso_em_silencio():
    # O WebSocket fecha uma conexão marcada; o app reconecta e pede o estado de novo.
    async def main():
        conn = Connection("u1", asyncio.get_running_loop(), max_queue=2)
        for i in range(3):
            conn.deliver({"i": i})
        await asyncio.sleep(0)
        return conn.overflowed, conn.queue.qsize()

    assert asyncio.run(main()) == (True, 2)
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/infra/test_stores_api.py tests/realtime/test_hub.py`
Expected: erro ao carregar os testes — `ImportError: cannot import name 'InMemoryJobMarks' from 'app.infra.redis_store'`.

- [ ] **Step 3: Implementar**

Altere `server/app/infra/redis_store.py`:

````diff
--- a/server/app/infra/redis_store.py
+++ b/server/app/infra/redis_store.py
@@ -22,6 +22,10 @@ class PositionStore(Protocol):
         self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
     ) -> list[tuple[str, GeoPoint]]: ...
 
+    def prune(self, now: float, max_age_s: float) -> int:
+        """Esquece quem não manda posição há mais de `max_age_s` (celular desligado, app fechado)."""
+        ...
+
 
 class InMemoryPositionStore:
     """Versão em memória, para testes e para o simulador."""
@@ -41,6 +45,12 @@ class InMemoryPositionStore:
     def get(self, rider_id: str) -> GeoPoint | None:
         return self._points.get(rider_id)
 
+    def prune(self, now: float, max_age_s: float) -> int:
+        gone = [rider_id for rider_id, seen in self._seen.items() if now - seen > max_age_s]
+        for rider_id in gone:
+            self.remove(rider_id)
+        return len(gone)
+
     def nearby(
         self, center: GeoPoint, radius_m: float, now: float, max_age_s: float = 30.0
     ) -> list[tuple[str, GeoPoint]]:
@@ -54,6 +64,18 @@ class InMemoryPositionStore:
         return [(rider_id, point) for _, rider_id, point in found]
 
 
+# Tirar quem sumiu numa ida só: lendo e apagando em comandos separados, uma posição nova que chegasse
+# no meio seria apagada junto.
+_PRUNE_LUA = """
+local old = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1])
+for _, id in ipairs(old) do
+    redis.call('zrem', KEYS[1], id)
+    redis.call('zrem', KEYS[2], id)
+end
+return #old
+"""
+
+
 class RedisPositionStore:
     GEO = "pos:geo"
     SEEN = "pos:seen"
@@ -65,6 +87,10 @@ class RedisPositionStore:
                 "(senão os ids dos motoqueiros voltam como bytes)"
             )
         self.r = client
+        self._prune = client.register_script(_PRUNE_LUA)
+
+    def prune(self, now: float, max_age_s: float) -> int:
+        return int(self._prune(keys=[self.GEO, self.SEEN], args=[repr(now - max_age_s)]))
 
     def update(self, rider_id: str, point: GeoPoint, now: float) -> None:
         pipe = self.r.pipeline()
@@ -176,3 +202,103 @@ class RedisFactorStore:
 
     def set(self, value: float, updated_at: float) -> None:
         self.r.set(self.key, f"{value!r}:{updated_at!r}")
+
+
+
+# --- limite de tentativas, saúde do Pix e marcas de tarefas diárias -------------------------------
+
+
+class RateLimiter(Protocol):
+    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
+        """Conta mais uma tentativa em `key`. Devolve False quando passou de `limit` na janela atual."""
+
+
+class InMemoryRateLimiter:
+    def __init__(self) -> None:
+        self._counts: dict[tuple[str, int], int] = {}
+
+    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
+        bucket = (key, int(now // window_s))
+        self._counts[bucket] = self._counts.get(bucket, 0) + 1
+        return self._counts[bucket] <= limit
+
+
+class RedisRateLimiter:
+    """Janela fixa por chave. O instante vem de quem chama (`now`), como no resto do servidor."""
+
+    def __init__(self, client: redis.Redis, prefix: str = "rl:") -> None:
+        self.r = client
+        self.prefix = prefix
+
+    def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
+        bucket = f"{self.prefix}{key}:{int(now // window_s)}"
+        pipe = self.r.pipeline()
+        pipe.incr(bucket)
+        pipe.expire(bucket, int(window_s * 2))
+        count, _ = pipe.execute()
+        return int(count) <= limit
+
+
+class PixHealth(Protocol):
+    def mark_down(self, now: float, for_s: float) -> None: ...
+
+    def is_down(self, now: float) -> bool: ...
+
+
+class InMemoryPixHealth:
+    def __init__(self) -> None:
+        self._down_until = 0.0
+
+    def mark_down(self, now: float, for_s: float) -> None:
+        self._down_until = max(self._down_until, now + for_s)
+
+    def is_down(self, now: float) -> bool:
+        return now < self._down_until
+
+
+class RedisPixHealth:
+    """O Pix é dado como fora do ar até um instante; passado esse instante, volta a ser tentado."""
+
+    def __init__(self, client: redis.Redis, key: str = "pix:down_until") -> None:
+        self.r = client
+        self.key = key
+
+    def mark_down(self, now: float, for_s: float) -> None:
+        until = max(self._until(), now + for_s)
+        self.r.set(self.key, repr(until), ex=int(for_s) + 60)
+
+    def _until(self) -> float:
+        raw = self.r.get(self.key)
+        return float(raw) if raw is not None else 0.0
+
+    def is_down(self, now: float) -> bool:
+        return now < self._until()
+
+
+class JobMarks(Protocol):
+    def get(self, name: str) -> str | None: ...
+
+    def set(self, name: str, value: str) -> None: ...
+
+
+class InMemoryJobMarks:
+    def __init__(self) -> None:
+        self._values: dict[str, str] = {}
+
+    def get(self, name: str) -> str | None:
+        return self._values.get(name)
+
+    def set(self, name: str, value: str) -> None:
+        self._values[name] = value
+
+
+class RedisJobMarks:
+    def __init__(self, client: redis.Redis, prefix: str = "job:") -> None:
+        self.r = client
+        self.prefix = prefix
+
+    def get(self, name: str) -> str | None:
+        return self.r.get(f"{self.prefix}{name}")
+
+    def set(self, name: str, value: str) -> None:
+        self.r.set(f"{self.prefix}{name}", value)
````

Crie o arquivo vazio `server/app/realtime/__init__.py`.

Crie `server/app/realtime/hub.py`:

````python
"""Quem está conectado por WebSocket e como os avisos chegam até essas conexões.

Os serviços rodam em threads comuns (as rotas são síncronas) e o WebSocket vive no laço assíncrono do
servidor. `Connection.deliver` faz a ponte com `call_soon_threadsafe`, então `Hub.publish` pode ser
chamado de qualquer thread. O aviso é uma dica: se a conexão cair ou a fila encher, o app reconecta e
pede o estado de novo (`/state`), que é a fonte da verdade.
"""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from collections.abc import Iterable

from app.services.events import Event


def to_message(event: Event, now: float) -> dict:
    return {"type": event.type, "data": event.payload, "at": now}


class Connection:
    def __init__(self, user_id: str, loop: asyncio.AbstractEventLoop, max_queue: int = 100) -> None:
        self.user_id = user_id
        self.loop = loop
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self.overflowed = False     # a fila encheu: quem lê fecha a conexão para o app pedir o estado de novo

    def _put(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True

    def deliver(self, message: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self._put, message)
        except RuntimeError:        # o laço já fechou: a conexão morreu entre o aviso e a entrega
            pass


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, set[Connection]] = defaultdict(set)

    def add(self, connection: Connection) -> None:
        with self._lock:
            self._connections[connection.user_id].add(connection)

    def remove(self, connection: Connection) -> None:
        with self._lock:
            group = self._connections.get(connection.user_id)
            if group is None:
                return
            group.discard(connection)
            if not group:
                del self._connections[connection.user_id]

    def publish(self, user_id: str, message: dict) -> int:
        """Entrega a todas as conexões do usuário. Devolve quantas receberam."""
        with self._lock:
            targets = list(self._connections.get(user_id, ()))
        for connection in targets:
            connection.deliver(message)
        return len(targets)

    def publish_events(self, events: Iterable[Event], now: float) -> None:
        for event in events:
            self.publish(event.user_id, to_message(event, now))

    def count(self) -> int:
        with self._lock:
            return sum(len(group) for group in self._connections.values())
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/infra/test_stores_api.py tests/realtime/test_hub.py`
Expected: `14 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `435 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(realtime): hub de avisos e lojas de apoio no Redis" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 4: O runtime: unidade de trabalho que grava antes de publicar

`Runtime.run` é o único caminho de uma rota até os serviços. Abre uma sessão, monta os serviços com **um** `EventCollector` só para aquele pedido, roda o trabalho, grava e só então publica os avisos. Erro desfaz tudo e descarta os avisos; impasse no banco repete o pedido inteiro. `build_runtime` liga tudo de verdade (e recusa subir fora do modo de desenvolvimento até o plano 7).

**Files:**
- Modify: `server/app/adapters/fake_otp.py`
- Modify: `server/app/api/app.py`
- Modify: `server/app/db/session.py`
- Create: `server/app/runtime.py`
- Test: `server/tests/api/conftest.py` (novo)
- Test: `server/tests/api/test_health.py` (novo)
- Test: `server/tests/api/test_runtime.py` (novo)

**Interfaces:**
- Consumes: todos os serviços do 2B, `load_app_config`, `Hub`, as lojas da Tarefa 3, `make_engine`/`make_session_factory`.
- Produces: `app.runtime.Unit` (`session, now, cfg, events, positions, auth, riders, payments, dispatch, trips, quotes, requests, sweeps`; a Tarefa 10 acrescenta `safety`), `Runtime(session_factory, positions, reservations, factors, maps, provider, otp_sender, hub, limiter, pix_health, job_marks, mode="production", clock=time.time, redis_client=None, ...)` com `config(session)`, `make_unit(session)`, `run(work, *, retries=2)`, `publish(events, now)`, `check()`; `build_runtime(settings)`; `DevOtpSender`; GET `/health`. Fixtures de teste: `runtime`, `client`, `clock` (relógio manual), `listen(user_id)` (guarda os avisos publicados).

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/api/conftest.py`:

````python
"""Montagem da API para os testes: banco de teste (com desfazer no fim), lojas em memória e relógio manual."""
import pytest
from fastapi.testclient import TestClient

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_otp import FakeOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.api.app import create_app
from app.domain.dispatch import ReservationBook
from app.infra.redis_store import (
    InMemoryFactorStore,
    InMemoryJobMarks,
    InMemoryPixHealth,
    InMemoryPositionStore,
    InMemoryRateLimiter,
)
from app.realtime.hub import Hub
from app.runtime import Runtime

AGORA = 1_800_000_000.0


class Clock:
    def __init__(self, now: float = AGORA) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Gravador:
    """Faz de conta de uma conexão WebSocket: guarda o que o servidor publicou para um usuário."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.messages: list[dict] = []

    def deliver(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def runtime(session, clock):
    return Runtime(
        session_factory=lambda: session,
        positions=InMemoryPositionStore(),
        reservations=ReservationBook(),
        factors=InMemoryFactorStore(),
        maps=FakeMaps(),
        provider=FakePaymentProvider(),
        otp_sender=FakeOtpSender(),
        hub=Hub(),
        limiter=InMemoryRateLimiter(),
        pix_health=InMemoryPixHealth(),
        job_marks=InMemoryJobMarks(),
        mode="dev",
        clock=clock,
    )


@pytest.fixture()
def client(runtime):
    with TestClient(create_app(runtime)) as c:
        yield c


@pytest.fixture()
def listen(runtime):
    """`listen("p1")` começa a guardar os avisos publicados para o usuário p1."""

    def _listen(user_id: str) -> Gravador:
        gravador = Gravador(user_id)
        runtime.hub.add(gravador)
        return gravador

    return _listen
````

Crie `server/tests/api/test_health.py`:

````python
def test_saude_responde_ok_com_banco_e_redis(client):
    resposta = client.get("/health")
    assert resposta.status_code == 200 and resposta.json() == {"status": "ok"}


def test_saude_devolve_503_quando_algo_falha(client, runtime):
    class SessaoRuim:
        def __enter__(self):
            raise RuntimeError("sem banco")

        def __exit__(self, *args):
            return False

    runtime.session_factory = lambda: SessaoRuim()
    resposta = client.get("/health")
    assert resposta.status_code == 503 and resposta.json() == {"status": "down"}


def test_documentacao_automatica_so_existe_no_modo_dev(client):
    assert client.get("/docs").status_code == 200
````

Crie `server/tests/api/test_runtime.py`:

````python
import dataclasses

import psycopg.errors
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.config_store import save_config
from app.db.models import UserRow
from app.domain.config import RideConfig
from app.runtime import Runtime, build_runtime
from tests.api.conftest import Gravador


def _usuario(unit, user_id="p1"):
    repo.add_user(unit.session, user_id=user_id, phone="+5575900000001", name="Ana", role="passenger")
    unit.events.add(user_id, "ola", {"a": 1})


def test_depois_do_commit_publica_os_avisos_da_unidade(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)
    runtime.run(lambda unit: _usuario(unit))
    assert gravador.types == ["ola"]
    assert gravador.messages[0]["data"] == {"a": 1}
    assert gravador.messages[0]["at"] == runtime.clock()
    assert session.get(UserRow, "p1") is not None


def test_o_commit_vem_antes_da_publicacao(runtime, session):
    ordem: list[str] = []

    class SessaoQueAnota(Session):
        def commit(self):
            ordem.append("commit")
            super().commit()

    class HubQueAnota:
        def publish_events(self, events, now):
            ordem.append("publica")

    sessao = SessaoQueAnota(bind=session.get_bind(), join_transaction_mode="create_savepoint", expire_on_commit=False)
    runtime.session_factory = lambda: sessao
    runtime.hub = HubQueAnota()
    runtime.run(lambda unit: unit.events.add("p1", "ola"))
    sessao.close()
    assert ordem == ["commit", "publica"]


def test_erro_no_meio_desfaz_o_banco_e_nao_publica_nada(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)

    def trabalho(unit):
        _usuario(unit)
        raise RuntimeError("quebrou")

    with pytest.raises(RuntimeError):
        runtime.run(trabalho)
    assert gravador.messages == []
    assert session.get(UserRow, "p1") is None


def _impasse():
    return OperationalError("UPDATE ...", {}, psycopg.errors.DeadlockDetected())


def test_impasse_no_banco_repete_a_unidade_com_avisos_novos(runtime, session):
    gravador = Gravador("p1")
    runtime.hub.add(gravador)
    tentativas = []

    def trabalho(unit):
        tentativas.append(unit.events)
        unit.events.add("p1", f"tentativa-{len(tentativas)}")
        if len(tentativas) == 1:
            raise _impasse()
        return "ok"

    assert runtime.run(trabalho) == "ok"
    assert len(tentativas) == 2 and tentativas[0] is not tentativas[1]
    assert gravador.types == ["tentativa-2"]          # o aviso da tentativa desfeita não sai


def test_impasse_que_nao_passa_depois_das_repeticoes_estoura(runtime):
    chamadas = []

    def trabalho(unit):
        chamadas.append(1)
        raise _impasse()

    with pytest.raises(OperationalError):
        runtime.run(trabalho, retries=2)
    assert len(chamadas) == 3


def test_outro_erro_do_banco_nao_e_repetido(runtime):
    chamadas = []

    def trabalho(unit):
        chamadas.append(1)
        raise OperationalError("SELECT 1", {}, psycopg.errors.AdminShutdown())

    with pytest.raises(OperationalError):
        runtime.run(trabalho)
    assert len(chamadas) == 1


def test_falha_ao_publicar_nao_derruba_o_pedido(runtime, session):
    class HubQuebrado:
        def publish_events(self, events, now):
            raise RuntimeError("hub caiu")

    runtime.hub = HubQuebrado()
    runtime.run(lambda unit: _usuario(unit))
    assert session.get(UserRow, "p1") is not None


def test_todos_os_servicos_da_unidade_dividem_o_mesmo_coletor(runtime):
    def trabalho(unit):
        return {
            unit.events, unit.riders.events, unit.payments.events, unit.dispatch.events, unit.trips.events,
            unit.requests.events, unit.sweeps.events,
        }

    assert len(runtime.run(trabalho)) == 1
    primeiro, segundo = runtime.run(lambda u: u.events), runtime.run(lambda u: u.events)
    assert primeiro is not segundo        # cada unidade de trabalho tem o seu; nunca um coletor global


def test_a_unidade_usa_o_relogio_do_servidor_e_a_configuracao_guardada(runtime, session, clock):
    assert runtime.run(lambda u: u.now) == clock.now
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 120
    save_config(session, "rides", dataclasses.replace(RideConfig(), pix_window_s=90))
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 120      # ainda no cache de 30 s
    clock.advance(31)
    assert runtime.run(lambda u: u.cfg.rides.pix_window_s) == 90
    assert runtime.run(lambda u: u.payments.ride_cfg.pix_window_s) == 90


def test_modo_de_producao_recusa_subir_com_adaptadores_falsos(settings):
    with pytest.raises(RuntimeError, match="plano 7"):
        build_runtime(dataclasses.replace(settings, mode="production"))


def test_modo_dev_monta_tudo_com_redis_de_verdade(settings, redis_test_url, redis_client):
    runtime = build_runtime(dataclasses.replace(settings, mode="dev", redis_url=redis_test_url))
    assert isinstance(runtime, Runtime) and runtime.mode == "dev"
    runtime.check()                                   # banco e Redis respondem
    assert runtime.positions.get("ninguem") is None
    assert runtime.pix_health.is_down(1.0) is False


def test_saude_acusa_quando_o_banco_nao_responde(runtime):
    class SessaoRuim:
        def __enter__(self):
            raise RuntimeError("sem banco")

        def __exit__(self, *args):
            return False

    runtime.session_factory = lambda: SessaoRuim()
    with pytest.raises(RuntimeError):
        runtime.check()
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_health.py tests/api/test_runtime.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.runtime'`.

- [ ] **Step 3: Implementar**

Altere `server/app/adapters/fake_otp.py`:

````diff
--- a/server/app/adapters/fake_otp.py
+++ b/server/app/adapters/fake_otp.py
@@ -1,6 +1,10 @@
 """Envio de código falso, para testes e para o simulador. Guarda o que "enviou"."""
 from __future__ import annotations
 
+import logging
+
+log = logging.getLogger("app.otp")
+
 
 class FakeOtpSender:
     def __init__(self) -> None:
@@ -11,3 +15,12 @@ class FakeOtpSender:
 
     def last_code(self, phone: str) -> str:
         return next(code for p, code in reversed(self.sent) if p == phone)
+
+
+class DevOtpSender(FakeOtpSender):
+    """Servidor de desenvolvimento: ainda não há WhatsApp (plano 7), então o código vai para o registro."""
+
+    def send(self, phone: str, code: str) -> None:
+        super().send(phone, code)
+        del self.sent[:-200]
+        log.info("código de login de %s: %s", phone, code)
````

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -2,6 +2,7 @@
 from __future__ import annotations
 
 from fastapi import FastAPI
+from fastapi.responses import JSONResponse
 
 from app.api.errors import install_error_handlers
 
@@ -18,4 +19,15 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     )
     app.state.runtime = runtime
     install_error_handlers(app)
+
+    if runtime is not None:
+
+        @app.get("/health")
+        def health():
+            try:
+                runtime.check()
+            except Exception:
+                return JSONResponse({"status": "down"}, status_code=503)
+            return {"status": "ok"}
+
     return app
````

Altere `server/app/db/session.py`:

````diff
--- a/server/app/db/session.py
+++ b/server/app/db/session.py
@@ -7,7 +7,7 @@ from app.settings import Settings
 
 
 def make_engine(settings: Settings) -> Engine:
-    return create_engine(settings.database_url, pool_pre_ping=True)
+    return create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
 
 
 def make_session_factory(engine: Engine) -> sessionmaker[Session]:
````

Crie `server/app/runtime.py`:

````python
"""Peças compartilhadas do servidor e a "unidade de trabalho" de cada pedido.

`Runtime.run` é o único caminho de uma rota até os serviços: abre uma sessão do banco, monta os serviços
com **um** `EventCollector` só para aquela unidade, roda o trabalho, faz o `commit` e só então publica
os avisos aos apps. Se der erro, desfaz o banco e descarta os avisos. Se o banco derrubar a transação
por impasse, repete a unidade inteira (com sessão e avisos novos).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_otp import DevOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.db.config_store import AppConfig, load_app_config
from app.db.session import make_engine, make_session_factory
from app.domain.maps import MapsProvider
from app.domain.payments import PaymentProvider
from app.infra.redis_store import (
    FactorStore,
    JobMarks,
    PixHealth,
    PositionStore,
    RateLimiter,
    RedisFactorStore,
    RedisJobMarks,
    RedisPixHealth,
    RedisPositionStore,
    RedisRateLimiter,
    RedisReservationBook,
)
from app.realtime.hub import Hub
from app.services.auth import AuthService, OtpSender
from app.services.dispatch import DispatchService, Reservations
from app.services.events import EventCollector
from app.services.payments import PaymentService
from app.services.quotes import QuoteService
from app.services.ride_requests import RideRequestService
from app.services.riders import RiderService
from app.services.sweeps import SweepService
from app.services.trips import TripService
from app.settings import Settings

log = logging.getLogger("app.runtime")

T = TypeVar("T")

_RETRYABLE_SQLSTATES = ("40P01", "40001")      # impasse (deadlock) e falha de serialização


@dataclass
class Unit:
    """Tudo o que uma rota precisa para trabalhar: sessão, hora, configuração e serviços."""

    session: Session
    now: float
    cfg: AppConfig
    events: EventCollector
    auth: AuthService
    riders: RiderService
    payments: PaymentService
    dispatch: DispatchService
    trips: TripService
    quotes: QuoteService
    requests: RideRequestService
    sweeps: SweepService


@dataclass
class Runtime:
    session_factory: Callable[[], Session]
    positions: PositionStore
    reservations: Reservations
    factors: FactorStore
    maps: MapsProvider
    provider: PaymentProvider
    otp_sender: OtpSender
    hub: Hub
    limiter: RateLimiter
    pix_health: PixHealth
    job_marks: JobMarks
    mode: str = "production"
    clock: Callable[[], float] = time.time
    redis_client: Any = None
    config_ttl_s: float = 30.0
    retry_pause_s: float = 0.02
    _config: tuple[float, AppConfig] | None = field(default=None, repr=False)

    # --- configuração ---------------------------------------------------------------------------

    def config(self, session: Session) -> AppConfig:
        """Parâmetros do banco, relidos a cada `config_ttl_s` (o dono muda no painel sem reiniciar)."""
        now = self.clock()
        if self._config is None or now - self._config[0] >= self.config_ttl_s:
            self._config = (now, load_app_config(session))
        return self._config[1]

    # --- unidade de trabalho --------------------------------------------------------------------

    def make_unit(self, session: Session) -> Unit:
        cfg = self.config(session)
        events = EventCollector()
        payments = PaymentService(self.provider, cfg.fees, cfg.rides, events)
        dispatch = DispatchService(self.positions, self.reservations, self.maps, payments, events, cfg)
        trips = TripService(payments, dispatch, events, cfg)
        return Unit(
            session=session, now=self.clock(), cfg=cfg, events=events,
            auth=AuthService(self.otp_sender, cfg.auth),
            riders=RiderService(self.positions, events, cfg.fees),
            payments=payments, dispatch=dispatch, trips=trips,
            quotes=QuoteService(self.maps, self.positions, self.factors, cfg),
            requests=RideRequestService(dispatch, events, cfg),
            sweeps=SweepService(payments, dispatch, trips, events, cfg),
        )

    def run(self, work: Callable[[Unit], T], *, retries: int = 2) -> T:
        for attempt in range(retries + 1):
            with self.session_factory() as session:
                unit = self.make_unit(session)
                try:
                    result = work(unit)
                    session.commit()
                except OperationalError as exc:
                    session.rollback()
                    if attempt < retries and getattr(exc.orig, "sqlstate", None) in _RETRYABLE_SQLSTATES:
                        log.warning("transação repetida (%s), tentativa %d", exc.orig.sqlstate, attempt + 1)
                        time.sleep(self.retry_pause_s)
                        continue
                    raise
                except BaseException:
                    session.rollback()
                    raise
            self.publish(unit.events.drain(), unit.now)
            return result
        raise AssertionError("inalcançável")      # o laço sempre devolve ou levanta

    def publish(self, events: list, now: float) -> None:
        """Entrega os avisos aos apps conectados. Uma falha aqui nunca derruba quem pediu."""
        if not events:
            return
        try:
            self.hub.publish_events(events, now)
        except Exception:
            log.exception("falha ao publicar %d aviso(s)", len(events))

    def check(self) -> None:
        """Levanta erro se o banco ou o Redis não responderem (usado em /health)."""
        with self.session_factory() as session:
            session.execute(text("SELECT 1"))
        if self.redis_client is not None:
            self.redis_client.ping()


def build_runtime(settings: Settings) -> Runtime:
    if settings.mode != "dev":
        raise RuntimeError(
            "Os adaptadores reais (Woovi, Google Maps, código por WhatsApp) são do plano 7. "
            "Por enquanto só existe o modo de desenvolvimento: defina APP_MODE=dev em server/.env."
        )
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return Runtime(
        session_factory=make_session_factory(make_engine(settings)),
        positions=RedisPositionStore(client),
        reservations=RedisReservationBook(client),
        factors=RedisFactorStore(client),
        maps=FakeMaps(),
        provider=FakePaymentProvider(),
        otp_sender=DevOtpSender(),
        hub=Hub(),
        limiter=RedisRateLimiter(client),
        pix_health=RedisPixHealth(client),
        job_marks=RedisJobMarks(client),
        mode="dev",
        redis_client=client,
    )
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_health.py tests/api/test_runtime.py`
Expected: `15 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `450 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): runtime com unidade de trabalho que grava antes de publicar" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 5: Entrar: rotas de login, papéis, administrador e linha de comando

Rotas de entrar (código, verificação, sair, meus dados), as dependências que descobrem quem chama e conferem o papel, o limite de pedidos de código por aparelho, o login de administrador (só para número já criado) e o comando `python -m app.cli create-admin`. Dois ajustes no `AuthService` do 2B: pedir outro código invalida o anterior, e o papel `admin`.

**Files:**
- Modify: `server/app/api/app.py`
- Create: `server/app/api/deps.py`
- Create: `server/app/api/routes/__init__.py`
- Create: `server/app/api/routes/auth.py`
- Create: `server/app/cli.py`
- Modify: `server/app/domain/config.py`
- Modify: `server/app/services/auth.py`
- Test: `server/tests/api/helpers.py` (novo)
- Test: `server/tests/api/test_auth_routes.py` (novo)
- Test: `server/tests/services/test_auth.py` (alterado)
- Test: `server/tests/test_cli.py` (novo)

**Interfaces:**
- Consumes: `Runtime.run`, `AuthService`, `AuthUser`, `ApiError`.
- Produces: `AuthConfig.otp_requests_per_ip_hour = 100`; `app.api.deps`: `get_runtime(request)`, `bearer_token(request)`, `current_user(request) -> AuthUser`, `require_role(*roles)`, `passenger_user`, `rider_user`, `admin_user`; rotas `/v1/auth/code`, `/v1/auth/verify`, `/v1/auth/logout`, `/v1/me` (GET e PUT); `app.cli.create_admin(session, raw_phone, name) -> str` e `main(argv, session_factory)`; ajudante de teste `tests/api/helpers.login(client, runtime, phone, role, name=None) -> Login(user_id, token, phone, role)` com `.headers`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/api/helpers.py`:

````python
"""Ajudantes dos testes da API: entrar com um número e montar o cabeçalho de autorização."""
from dataclasses import dataclass

from app.services.auth import normalize_phone


@dataclass(frozen=True)
class Login:
    user_id: str
    token: str
    phone: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def login(client, runtime, phone: str, role: str, name: str | None = None) -> Login:
    resposta = client.post("/v1/auth/code", json={"phone": phone})
    assert resposta.status_code == 204, resposta.text
    codigo = runtime.otp_sender.last_code(normalize_phone(phone))
    resposta = client.post("/v1/auth/verify", json={"phone": phone, "code": codigo, "role": role, "device": "teste"})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    entrou = Login(corpo["user_id"], corpo["token"], normalize_phone(phone))
    if name:
        assert client.put("/v1/me", json={"name": name}, headers=entrou.headers).status_code == 200
    return entrou
````

Crie `server/tests/api/test_auth_routes.py`:

````python
import pytest
from fastapi import Depends

from app.api.deps import admin_user, passenger_user, rider_user
from app.db import repositories as repo
from app.db.config_store import save_config
from app.db.models import SessionRow, UserRow
from app.domain.config import AuthConfig
from app.services.auth import normalize_phone
from tests.api.helpers import login

PHONE = "75 99999-1234"


def _pedir_codigo(client, runtime, phone=PHONE) -> str:
    assert client.post("/v1/auth/code", json={"phone": phone}).status_code == 204
    return runtime.otp_sender.last_code(normalize_phone(phone))


def test_entrar_ver_meus_dados_dar_nome_e_sair(client, runtime):
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post(
        "/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger", "device": "Moto G"}
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["role"] == "passenger" and corpo["is_new_user"] is True and corpo["name"] == ""
    cabecalho = {"Authorization": f"Bearer {corpo['token']}"}

    assert client.get("/v1/me", headers=cabecalho).json() == {
        "user_id": corpo["user_id"], "phone": "+5575999991234", "name": "", "role": "passenger",
    }
    assert client.put("/v1/me", json={"name": " Ana Lima "}, headers=cabecalho).json()["name"] == "Ana Lima"
    assert client.post("/v1/auth/logout", headers=cabecalho).status_code == 204
    assert client.get("/v1/me", headers=cabecalho).status_code == 401


def test_segundo_login_devolve_o_nome_ja_guardado(client, runtime):
    primeiro = login(client, runtime, PHONE, "passenger", name="Ana Lima")
    codigo = _pedir_codigo(client, runtime)
    corpo = client.post(
        "/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger", "device": "Outro"}
    ).json()
    assert corpo["user_id"] == primeiro.user_id and corpo["is_new_user"] is False and corpo["name"] == "Ana Lima"


def test_codigo_errado_conta_tentativa_mesmo_com_erro_e_cinco_erros_travam(client, runtime):
    # O erro volta como 401, mas a contagem de tentativas precisa ficar gravada (a unidade faz commit).
    certo = _pedir_codigo(client, runtime)
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):
        resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": errado, "role": "passenger"})
        assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "code_invalid"
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": certo, "role": "passenger"})
    assert resposta.status_code == 401 and "tentativas" in resposta.json()["error"]["message"]


def test_celular_invalido_e_papel_invalido_sao_recusados(client):
    resposta = client.post("/v1/auth/code", json={"phone": "12345"})
    assert resposta.status_code == 422 and resposta.json()["error"]["code"] == "invalid"
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": "123456", "role": "chefe"})
    assert resposta.status_code == 422 and resposta.json()["error"]["fields"] == ["role"]


def test_pedir_codigo_demais_para_o_mesmo_numero_da_429(client, runtime):
    for _ in range(5):
        assert client.post("/v1/auth/code", json={"phone": PHONE}).status_code == 204
    resposta = client.post("/v1/auth/code", json={"phone": PHONE})
    assert resposta.status_code == 429 and resposta.json()["error"]["code"] == "too_many_requests"


def test_pedir_codigo_demais_do_mesmo_aparelho_para_numeros_diferentes_da_429(client, runtime, session):
    save_config(session, "auth", AuthConfig(otp_requests_per_ip_hour=3))
    for n in range(3):
        assert client.post("/v1/auth/code", json={"phone": f"75 99999-000{n}"}).status_code == 204
    resposta = client.post("/v1/auth/code", json={"phone": "75 99999-0009"})
    assert resposta.status_code == 429


@pytest.mark.parametrize("cabecalho", [None, "", "Bearer", "Bearer    ", "Basic abc", "Bearer token-inventado"])
def test_sem_token_ou_com_token_ruim_e_401(client, cabecalho):
    headers = {} if cabecalho is None else {"Authorization": cabecalho}
    resposta = client.get("/v1/me", headers=headers)
    assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "unauthorized"


def test_conta_bloqueada_perde_o_acesso_na_hora(client, runtime, session):
    entrou = login(client, runtime, PHONE, "passenger")
    session.get(UserRow, entrou.user_id).is_blocked = True
    session.flush()
    assert client.get("/v1/me", headers=entrou.headers).status_code == 401


def test_sessao_vencida_e_401(client, runtime, session, clock):
    entrou = login(client, runtime, PHONE, "passenger")
    clock.advance(181 * 86400)
    assert client.get("/v1/me", headers=entrou.headers).status_code == 401
    assert session.query(SessionRow).count() == 1


def test_cada_papel_so_entra_nas_rotas_do_seu_papel(client, runtime):
    client.app.add_api_route("/t/passageiro", lambda u=Depends(passenger_user): {"ok": u.role}, methods=["GET"])
    client.app.add_api_route("/t/motoqueiro", lambda u=Depends(rider_user): {"ok": u.role}, methods=["GET"])
    client.app.add_api_route("/t/admin", lambda u=Depends(admin_user): {"ok": u.role}, methods=["GET"])
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    motoqueiro = login(client, runtime, "75 99999-0002", "rider")
    assert client.get("/t/passageiro", headers=passageiro.headers).json() == {"ok": "passenger"}
    assert client.get("/t/motoqueiro", headers=motoqueiro.headers).json() == {"ok": "rider"}
    for rota, quem in (("/t/motoqueiro", passageiro), ("/t/passageiro", motoqueiro), ("/t/admin", passageiro)):
        resposta = client.get(rota, headers=quem.headers)
        assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "wrong_role"


def test_administrador_entra_so_se_ja_existir(client, runtime, session):
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "admin"})
    assert resposta.status_code == 401 and "administrador" in resposta.json()["error"]["message"]
    repo.add_user(session, user_id="adm-1", phone="+5575999991234", name="Levy", role="admin")
    entrou = login(client, runtime, PHONE, "admin")
    assert client.get("/v1/me", headers=entrou.headers).json()["role"] == "admin"


def test_numero_de_motoqueiro_nao_entra_como_passageiro(client, runtime):
    login(client, runtime, PHONE, "rider")
    codigo = _pedir_codigo(client, runtime)
    resposta = client.post("/v1/auth/verify", json={"phone": PHONE, "code": codigo, "role": "passenger"})
    assert resposta.status_code == 401 and "motoqueiro" in resposta.json()["error"]["message"]


def test_nome_curto_demais_e_recusado(client, runtime):
    entrou = login(client, runtime, PHONE, "passenger")
    resposta = client.put("/v1/me", json={"name": " "}, headers=entrou.headers)
    assert resposta.status_code == 422 and "nome" in resposta.json()["error"]["message"]
````

Altere `server/tests/services/test_auth.py`:

````diff
--- a/server/tests/services/test_auth.py
+++ b/server/tests/services/test_auth.py
@@ -138,3 +138,32 @@ def test_nome_do_usuario(auth, sender, session):
     assert auth.authenticate(session, entrou.token, 1100.0).name == "Ana Lima"
     with pytest.raises(ValueError, match="nome"):
         auth.set_name(session, entrou.user_id, " ")
+
+
+def test_pedir_codigo_de_novo_invalida_o_anterior(auth, sender, session):
+    # Roteiro do 2B (menores): um código antigo não pode continuar valendo depois de outro ter sido usado.
+    auth.request_code(session, PHONE, 1000.0)
+    antigo = sender.last_code(NORMAL)
+    auth.request_code(session, PHONE, 1010.0)
+    novo = sender.last_code(NORMAL)
+    assert antigo != novo
+    assert auth.verify_code(session, PHONE, novo, "passenger", "x", 1020.0).ok is True
+    assert auth.verify_code(session, PHONE, antigo, "passenger", "x", 1030.0).ok is False
+
+
+def test_administrador_so_entra_se_o_numero_ja_for_de_administrador(auth, sender, session):
+    auth.request_code(session, PHONE, 1000.0)
+    sem_acesso = auth.verify_code(session, PHONE, sender.last_code(NORMAL), "admin", "painel", 1001.0)
+    assert sem_acesso.ok is False and "administrador" in sem_acesso.reason
+    assert session.execute(select(UserRow).where(UserRow.phone == NORMAL)).first() is None   # não criou conta
+
+    repo.add_user(session, user_id="adm-1", phone=NORMAL, name="Levy", role="admin")
+    auth.request_code(session, PHONE, 2000.0)
+    entrou = auth.verify_code(session, PHONE, sender.last_code(NORMAL), "admin", "painel", 2001.0)
+    assert entrou.ok and entrou.role == "admin" and entrou.user_id == "adm-1" and not entrou.is_new_user
+
+
+def test_passageiro_nao_entra_como_administrador(auth, sender, session):
+    _login(auth, sender, session, role="passenger")
+    resultado = _login(auth, sender, session, now=5000.0, role="admin")
+    assert resultado.ok is False and "passageiro" in resultado.reason
````

Crie `server/tests/test_cli.py`:

````python
import pytest
from sqlalchemy import select

from app.cli import create_admin, main
from app.db import repositories as repo
from app.db.models import UserRow


def test_cria_o_administrador_com_o_numero_normalizado(session):
    user_id = create_admin(session, "75 99999-0000", "Levy")
    user = session.get(UserRow, user_id)
    assert (user.phone, user.name, user.role, user.is_blocked) == ("+5575999990000", "Levy", "admin", False)


def test_repetir_o_comando_nao_cria_outro(session):
    primeiro = create_admin(session, "75 99999-0000", "Levy")
    assert create_admin(session, "(75) 99999-0000", "Levy") == primeiro
    assert len(session.execute(select(UserRow)).all()) == 1


def test_numero_de_passageiro_nao_vira_administrador(session):
    repo.add_user(session, user_id="p1", phone="+5575999990000", name="Ana", role="passenger")
    with pytest.raises(ValueError, match="passageiro"):
        create_admin(session, "75 99999-0000", "Levy")


def test_numero_invalido_da_erro_claro(session):
    with pytest.raises(ValueError, match="celular"):
        create_admin(session, "123", "Levy")


def test_linha_de_comando_cria_e_avisa(session, capsys):
    codigo = main(["create-admin", "--phone", "75 99999-0000", "--name", "Levy"], session_factory=lambda: session)
    assert codigo == 0 and "Administrador pronto" in capsys.readouterr().out
    codigo = main(["create-admin", "--phone", "123", "--name", "Levy"], session_factory=lambda: session)
    assert codigo == 1 and "celular" in capsys.readouterr().err
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_auth_routes.py tests/services/test_auth.py tests/test_cli.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.api.deps'`.

- [ ] **Step 3: Implementar**

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -5,6 +5,7 @@ from fastapi import FastAPI
 from fastapi.responses import JSONResponse
 
 from app.api.errors import install_error_handlers
+from app.api.routes import auth as auth_routes
 
 
 def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
@@ -19,6 +20,7 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     )
     app.state.runtime = runtime
     install_error_handlers(app)
+    app.include_router(auth_routes.router)
 
     if runtime is not None:
 
````

Crie `server/app/api/deps.py`:

````python
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
````

Crie o arquivo vazio `server/app/api/routes/__init__.py`.

Crie `server/app/api/routes/auth.py`:

````python
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
````

Crie `server/app/cli.py`:

````python
"""Comandos de manutenção. Uso (a partir de `server/`):

    .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy"
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import UserRow
from app.domain.ids import new_id
from app.services.auth import normalize_phone


def create_admin(session: Session, raw_phone: str, name: str) -> str:
    """Cria o administrador (ou devolve o que já existe com este número). Devolve o id."""
    phone = normalize_phone(raw_phone)
    existing = session.execute(select(UserRow).where(UserRow.phone == phone)).scalar_one_or_none()
    if existing is not None:
        if existing.role != "admin":
            raise ValueError(f"Este número já é de {'passageiro' if existing.role == 'passenger' else 'motoqueiro'}.")
        return existing.id
    user_id = new_id("adm")
    repo.add_user(session, user_id=user_id, phone=phone, name=name.strip(), role="admin")
    return user_id


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="cria o acesso de administrador do painel")
    admin.add_argument("--phone", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    if session_factory is None:
        from app.db.session import make_engine, make_session_factory
        from app.settings import load_settings

        session_factory = make_session_factory(make_engine(load_settings()))
    try:
        with session_factory() as session:
            user_id = create_admin(session, args.phone, args.name)
            session.commit()
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(f"Administrador pronto: {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
````

Altere `server/app/domain/config.py`:

````diff
--- a/server/app/domain/config.py
+++ b/server/app/domain/config.py
@@ -81,4 +81,5 @@ class AuthConfig:
     otp_ttl_s: int = 300
     otp_max_attempts: int = 5
     otp_requests_per_hour: int = 5
+    otp_requests_per_ip_hour: int = 100   # por aparelho/rede; alto porque várias pessoas dividem o mesmo IP no 4G
     session_days: int = 180
````

Altere `server/app/services/auth.py`:

````diff
--- a/server/app/services/auth.py
+++ b/server/app/services/auth.py
@@ -13,7 +13,7 @@ import uuid
 from dataclasses import dataclass
 from typing import Protocol
 
-from sqlalchemy import func, select
+from sqlalchemy import func, select, update
 from sqlalchemy.orm import Session
 
 from app.db import repositories as repo
@@ -82,6 +82,10 @@ class AuthService:
         ).scalar_one()
         if recent >= self.cfg.otp_requests_per_hour:
             raise TooManyRequests("Muitos pedidos de código. Tente de novo mais tarde.")
+        # um código só vale por vez: pedir outro invalida o anterior
+        session.execute(
+            update(OtpCodeRow).where(OtpCodeRow.phone == phone, OtpCodeRow.used.is_(False)).values(used=True)
+        )
         digits = self.cfg.otp_digits
         code = f"{secrets.randbelow(10 ** digits):0{digits}d}"
         session.add(
@@ -95,7 +99,7 @@ class AuthService:
     def verify_code(
         self, session: Session, raw_phone: str, code: str, role: str, device: str, now: float
     ) -> LoginResult:
-        if role not in ("passenger", "rider"):
+        if role not in ("passenger", "rider", "admin"):
             raise ValueError("papel inválido")
         phone = normalize_phone(raw_phone)
         row = session.execute(
@@ -114,6 +118,8 @@ class AuthService:
             session.flush()
             return LoginResult(False, reason="Código errado.")
         user = session.execute(select(UserRow).where(UserRow.phone == phone)).scalar_one_or_none()
+        if user is None and role == "admin":      # administrador nunca nasce por login: é criado por `app.cli`
+            return LoginResult(False, reason="Este número não tem acesso de administrador.")
         if user is not None and user.role != role:
             return LoginResult(False, reason=f"Este número já tem cadastro de {_ROLE_NAMES.get(user.role, user.role)}.")
         if user is not None and user.is_blocked:
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_auth_routes.py tests/services/test_auth.py tests/test_cli.py`
Expected: `49 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `476 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): login por código, papéis, administrador e linha de comando" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 6: Cadastro do motoqueiro: fotos, cadastro, aprovação pelo dono e ver documentos

Fotos dos documentos (guardadas em disco, com o tipo conferido pelo conteúdo e teto de 8 MB), cadastro e renovação, e o mínimo do dono para andar: ver a fila, aprovar, recusar, bloquear e liberar, e ver as fotos. Fecha o item do 2B sobre cadastro concorrente que vazava `IntegrityError`.

**Files:**
- Modify: `server/app/api/app.py`
- Modify: `server/app/api/errors.py`
- Create: `server/app/api/routes/admin.py`
- Create: `server/app/api/routes/files.py`
- Create: `server/app/api/routes/rider.py`
- Modify: `server/app/db/queries.py`
- Create: `server/app/infra/documents.py`
- Modify: `server/app/runtime.py`
- Modify: `server/app/services/riders.py`
- Test: `server/tests/api/conftest.py` (alterado)
- Test: `server/tests/api/helpers.py` (alterado)
- Test: `server/tests/api/test_rider_onboarding.py` (novo)
- Test: `server/tests/infra/test_documents.py` (novo)
- Test: `server/tests/services/test_riders_api.py` (novo)

**Interfaces:**
- Consumes: `RiderService`, `ApiError`, `rider_user`, `admin_user`, `current_user`, `Runtime.run`.
- Produces: `app.infra.documents`: `KINDS`, `MAX_UPLOAD_BYTES`, `UploadError(status, code, message)`, `sniff_image(data) -> (ext, media_type)`, `DocumentStore` (`save(owner_id, kind, data) -> key`, `read(key) -> (bytes, media_type)`, `exists(key)`), `LocalDocumentStore(root)`; `Runtime.documents`; `RiderService._find_duplicate(session, *, cpf, cnh_number, plate)` e `renew_documents(..., cnh_photo_key=None, crlv_key=None)`; `queries.list_riders(session, status, limit, offset)`, `rider_document_key(session, rider_id, kind)`, `passenger_rode_with(session, passenger_id, rider_id)`; rotas `/v1/rider/documents/{kind}` (PUT), `/v1/rider/register`, `/v1/rider/documents/renew`, `/v1/admin/riders...`, `/v1/riders/{id}/documents/{kind}`.

- [ ] **Step 1: Escrever os testes que falham**

Altere `server/tests/api/conftest.py`:

````diff
--- a/server/tests/api/conftest.py
+++ b/server/tests/api/conftest.py
@@ -7,6 +7,7 @@ from app.adapters.fake_otp import FakeOtpSender
 from app.adapters.fake_payments import FakePaymentProvider
 from app.api.app import create_app
 from app.domain.dispatch import ReservationBook
+from app.infra.documents import LocalDocumentStore
 from app.infra.redis_store import (
     InMemoryFactorStore,
     InMemoryJobMarks,
@@ -52,7 +53,7 @@ def clock():
 
 
 @pytest.fixture()
-def runtime(session, clock):
+def runtime(session, clock, tmp_path):
     return Runtime(
         session_factory=lambda: session,
         positions=InMemoryPositionStore(),
@@ -65,6 +66,7 @@ def runtime(session, clock):
         limiter=InMemoryRateLimiter(),
         pix_health=InMemoryPixHealth(),
         job_marks=InMemoryJobMarks(),
+        documents=LocalDocumentStore(tmp_path / "docs"),
         mode="dev",
         clock=clock,
     )
````

Altere `server/tests/api/helpers.py`:

````diff
--- a/server/tests/api/helpers.py
+++ b/server/tests/api/helpers.py
@@ -9,6 +9,7 @@ class Login:
     user_id: str
     token: str
     phone: str
+    role: str
 
     @property
     def headers(self) -> dict[str, str]:
@@ -22,7 +23,7 @@ def login(client, runtime, phone: str, role: str, name: str | None = None) -> Lo
     resposta = client.post("/v1/auth/verify", json={"phone": phone, "code": codigo, "role": role, "device": "teste"})
     assert resposta.status_code == 200, resposta.text
     corpo = resposta.json()
-    entrou = Login(corpo["user_id"], corpo["token"], normalize_phone(phone))
+    entrou = Login(corpo["user_id"], corpo["token"], normalize_phone(phone), role)
     if name:
         assert client.put("/v1/me", json={"name": name}, headers=entrou.headers).status_code == 200
     return entrou
````

Crie `server/tests/api/test_rider_onboarding.py`:

````python
import datetime as dt

import pytest

from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from app.domain.clock import local_date
from app.infra.documents import MAX_UPLOAD_BYTES
from tests.api.helpers import login
from tests.helpers_db import make_cpf

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
CPF = make_cpf("123456789")


def subir(client, quem, kind, dados=JPEG):
    resposta = client.put(f"/v1/rider/documents/{kind}", content=dados, headers=quem.headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["key"]


def cadastro(client, quem, hoje, **mudar):
    corpo = dict(
        name="Carlos Moto", cpf=CPF, cnh_number="12345678901", plate="abc-1d23", moto_model="Honda CG 160",
        cnh_expires_on=str(hoje + dt.timedelta(days=700)), crlv_expires_on=str(hoje + dt.timedelta(days=300)),
    )
    corpo.update(mudar)
    for campo, kind in (("selfie_key", "selfie"), ("cnh_photo_key", "cnh"), ("crlv_key", "crlv")):
        if campo not in corpo:
            corpo[campo] = subir(client, quem, kind) if quem.role == "rider" else f"x/{kind}-0123456789abcdef.jpg"
    return client.post("/v1/rider/register", json=corpo, headers=quem.headers)


@pytest.fixture()
def hoje(clock):
    return local_date(clock.now)


@pytest.fixture()
def rider(client, runtime):
    return login(client, runtime, "75 99999-0002", "rider")


@pytest.fixture()
def admin(client, runtime, session):
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    return login(client, runtime, "75 99999-0000", "admin")


# --- envio de documentos ---------------------------------------------------------------------


def test_envia_a_foto_e_recebe_uma_chave_do_proprio_motoqueiro(client, rider):
    chave = subir(client, rider, "selfie")
    assert chave.startswith(f"{rider.user_id}/selfie-")


def test_so_motoqueiro_envia_documento(client, runtime):
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    resposta = client.put("/v1/rider/documents/selfie", content=JPEG, headers=passageiro.headers)
    assert resposta.status_code == 403
    assert client.put("/v1/rider/documents/selfie", content=JPEG).status_code == 401


@pytest.mark.parametrize(
    "dados, status, codigo",
    [
        (b"<html>oi</html>", 415, "not_an_image"),
        (b"", 422, "empty_file"),
        (b"%PDF-1.4 ...", 415, "not_an_image"),
    ],
)
def test_arquivo_que_nao_e_foto_e_recusado(client, rider, dados, status, codigo):
    resposta = client.put("/v1/rider/documents/cnh", content=dados, headers=rider.headers)
    assert resposta.status_code == status and resposta.json()["error"]["code"] == codigo


def test_arquivo_grande_demais_e_recusado_sem_guardar(client, rider, runtime, tmp_path):
    grande = JPEG + b"0" * MAX_UPLOAD_BYTES
    resposta = client.put("/v1/rider/documents/cnh", content=grande, headers=rider.headers)
    assert resposta.status_code == 413 and resposta.json()["error"]["code"] == "file_too_large"
    assert list(runtime.documents.root.rglob("*.jpg")) == []


def test_arquivo_grande_demais_sem_tamanho_declarado_tambem_e_cortado(client, rider):
    def pedacos():
        yield JPEG
        for _ in range(9):
            yield b"0" * (1024 * 1024)

    resposta = client.put("/v1/rider/documents/cnh", content=pedacos(), headers=rider.headers)
    assert resposta.status_code == 413


def test_tipo_de_documento_invalido_e_422(client, rider):
    assert client.put("/v1/rider/documents/senha", content=JPEG, headers=rider.headers).status_code == 422


def test_limite_de_envios_por_hora(client, rider, clock):
    for _ in range(30):
        subir(client, rider, "selfie")
    resposta = client.put("/v1/rider/documents/selfie", content=JPEG, headers=rider.headers)
    assert resposta.status_code == 429
    clock.advance(3600)
    assert client.put("/v1/rider/documents/selfie", content=JPEG, headers=rider.headers).status_code == 201


# --- cadastro --------------------------------------------------------------------------------


def test_cadastro_fica_pendente_e_guarda_os_dados_limpos(client, rider, session, hoje):
    resposta = cadastro(client, rider, hoje)
    assert resposta.status_code == 201 and resposta.json() == {"status": "pending"}
    perfil = session.get(RiderProfileRow, rider.user_id)
    assert (perfil.status, perfil.plate, perfil.online) == ("pending", "ABC1D23", False)
    assert session.get(UserRow, rider.user_id).name == "Carlos Moto"


def test_cadastro_com_dado_ruim_diz_o_que_conferir(client, rider, hoje):
    resposta = cadastro(client, rider, hoje, cpf="123.456.789-00")
    assert resposta.status_code == 422 and "CPF" in resposta.json()["error"]["message"]
    resposta = cadastro(client, rider, hoje, plate="XX")
    assert "placa" in resposta.json()["error"]["message"]


def test_cadastro_exige_fotos_enviadas_pelo_proprio_motoqueiro(client, runtime, rider, hoje):
    outro = login(client, runtime, "75 99999-0003", "rider")
    chave_do_outro = subir(client, outro, "selfie")
    resposta = cadastro(client, rider, hoje, selfie_key=chave_do_outro)
    assert resposta.status_code == 422 and "selfie" in resposta.json()["error"]["message"].lower()
    resposta = cadastro(client, rider, hoje, crlv_key=f"{rider.user_id}/crlv-0123456789abcdef.jpg")   # não existe
    assert resposta.status_code == 422
    resposta = cadastro(client, rider, hoje, cnh_photo_key=subir(client, rider, "selfie"))            # tipo trocado
    assert resposta.status_code == 422


def test_cadastro_repetido_do_mesmo_cpf_diz_o_campo(client, runtime, rider, hoje):
    assert cadastro(client, rider, hoje).status_code == 201
    outro = login(client, runtime, "75 99999-0003", "rider")
    resposta = cadastro(client, outro, hoje, cnh_number="99999999999", plate="ZZZ9Z99")
    assert resposta.status_code == 409
    assert resposta.json()["error"] == {
        "code": "duplicate_registration", "message": "Já existe um cadastro com este CPF.", "field": "CPF",
    }


def test_cadastro_so_uma_vez_e_so_de_motoqueiro(client, runtime, rider, hoje):
    assert cadastro(client, rider, hoje).status_code == 201
    assert cadastro(client, rider, hoje).status_code == 422
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    assert cadastro(client, passageiro, hoje).status_code == 403


# --- aprovação pelo administrador ------------------------------------------------------------


def test_so_administrador_ve_e_decide_cadastros(client, rider, hoje):
    cadastro(client, rider, hoje)
    assert client.get("/v1/admin/riders", headers=rider.headers).status_code == 403
    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=rider.headers).status_code == 403
    assert client.get("/v1/admin/riders").status_code == 401


def test_fila_de_cadastros_aprovar_recusar_bloquear_e_liberar(client, runtime, rider, admin, hoje, session, listen):
    avisos = listen(rider.user_id)
    cadastro(client, rider, hoje)
    fila = client.get("/v1/admin/riders", params={"status": "pending"}, headers=admin.headers).json()
    assert [r["rider_id"] for r in fila] == [rider.user_id]
    assert fila[0]["name"] == "Carlos Moto" and fila[0]["plate"] == "ABC1D23" and fila[0]["status"] == "pending"
    assert fila[0]["cpf"] == f"{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}"
    assert set(fila[0]["documents"]) == {"selfie", "cnh", "crlv"}

    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).status == "approved"
    assert avisos.types == ["rider_approved"]                       # o aviso sai depois do commit
    assert client.get("/v1/admin/riders", params={"status": "pending"}, headers=admin.headers).json() == []

    resposta = client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"

    corpo = {"reason": "Documento ilegível"}
    assert client.post(f"/v1/admin/riders/{rider.user_id}/block", json=corpo, headers=admin.headers).status_code == 204
    assert client.get("/v1/me", headers=rider.headers).status_code == 401      # bloqueado perde o acesso
    assert client.post(f"/v1/admin/riders/{rider.user_id}/unblock", headers=admin.headers).status_code == 204
    assert client.get("/v1/me", headers=rider.headers).status_code == 200


def test_recusar_cadastro_guarda_o_motivo(client, rider, admin, hoje, session):
    cadastro(client, rider, hoje)
    resposta = client.post(
        f"/v1/admin/riders/{rider.user_id}/reject", json={"reason": "CNH vencida na foto"}, headers=admin.headers
    )
    assert resposta.status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).rejected_reason == "CNH vencida na foto"
    sem_motivo = client.post(f"/v1/admin/riders/{rider.user_id}/reject", json={"reason": ""}, headers=admin.headers)
    assert sem_motivo.status_code == 422


def test_decidir_motoqueiro_que_nao_existe_e_404(client, admin):
    assert client.post("/v1/admin/riders/ninguem/approve", headers=admin.headers).status_code == 404


def test_lista_do_administrador_filtra_por_situacao_e_pagina(client, runtime, rider, admin, hoje):
    cadastro(client, rider, hoje)
    assert client.get("/v1/admin/riders", params={"status": "approved"}, headers=admin.headers).json() == []
    assert client.get("/v1/admin/riders", params={"status": "qualquer"}, headers=admin.headers).status_code == 422
    assert client.get("/v1/admin/riders", params={"limit": 0}, headers=admin.headers).status_code == 422
    assert client.get("/v1/admin/riders", params={"offset": 5}, headers=admin.headers).json() == []


# --- documentos vencidos e renovação ----------------------------------------------------------


def test_renovar_documentos_troca_datas_e_fotos(client, rider, hoje, session):
    cadastro(client, rider, hoje)
    nova = subir(client, rider, "cnh")
    corpo = {
        "cnh_expires_on": str(hoje + dt.timedelta(days=900)), "crlv_expires_on": str(hoje + dt.timedelta(days=400)),
        "cnh_photo_key": nova,
    }
    assert client.post("/v1/rider/documents/renew", json=corpo, headers=rider.headers).status_code == 204
    perfil = session.get(RiderProfileRow, rider.user_id)
    assert perfil.cnh_photo_key == nova and perfil.cnh_expires_on == hoje + dt.timedelta(days=900)


def test_renovar_com_data_vencida_ou_foto_alheia_e_recusado(client, runtime, rider, hoje):
    cadastro(client, rider, hoje)
    vencida = {"cnh_expires_on": str(hoje - dt.timedelta(days=1)), "crlv_expires_on": str(hoje + dt.timedelta(days=9))}
    assert client.post("/v1/rider/documents/renew", json=vencida, headers=rider.headers).status_code == 422
    outro = login(client, runtime, "75 99999-0003", "rider")
    alheia = {
        "cnh_expires_on": str(hoje + dt.timedelta(days=9)), "crlv_expires_on": str(hoje + dt.timedelta(days=9)),
        "crlv_key": subir(client, outro, "crlv"),
    }
    assert client.post("/v1/rider/documents/renew", json=alheia, headers=rider.headers).status_code == 422


# --- ver os documentos ------------------------------------------------------------------------


def test_quem_pode_ver_cada_documento(client, runtime, rider, admin, hoje, session):
    cadastro(client, rider, hoje)
    passageiro = login(client, runtime, "75 99999-0001", "passenger")
    outro_motoqueiro = login(client, runtime, "75 99999-0003", "rider")
    url = f"/v1/riders/{rider.user_id}/documents"

    for quem in (admin, rider):
        for kind in ("selfie", "cnh", "crlv"):
            resposta = client.get(f"{url}/{kind}", headers=quem.headers)
            assert resposta.status_code == 200 and resposta.content == JPEG
            assert resposta.headers["content-type"] == "image/jpeg"
            assert resposta.headers["cache-control"] == "private, max-age=3600"
            assert resposta.headers["x-content-type-options"] == "nosniff"

    # passageiro sem corrida com este motoqueiro, outro motoqueiro e visitante: nada
    assert client.get(f"{url}/selfie", headers=passageiro.headers).status_code == 403
    assert client.get(f"{url}/selfie", headers=outro_motoqueiro.headers).status_code == 403
    assert client.get(f"{url}/selfie").status_code == 401

    # passageiro que fez corrida com ele vê só a selfie, nunca a CNH nem o documento da moto
    from app.db.models import RideRow

    session.add(
        RideRow(
            id="ride-1", passenger_id=passageiro.user_id, rider_id=rider.user_id, price_cents=700,
            payment_method="cash", pin="1234", state="completed",
        )
    )
    session.flush()
    assert client.get(f"{url}/selfie", headers=passageiro.headers).status_code == 200
    assert client.get(f"{url}/cnh", headers=passageiro.headers).status_code == 403
    assert client.get(f"{url}/crlv", headers=passageiro.headers).status_code == 403


def test_documento_de_quem_nao_se_cadastrou_e_404(client, admin, rider):
    assert client.get(f"/v1/riders/{rider.user_id}/documents/selfie", headers=admin.headers).status_code == 404
    assert client.get("/v1/riders/ninguem/documents/selfie", headers=admin.headers).status_code == 404
````

Crie `server/tests/infra/test_documents.py`:

````python
import os
import stat

import pytest

from app.infra.documents import LocalDocumentStore, UploadError, sniff_image

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 64


@pytest.mark.parametrize(
    "dados, ext, tipo",
    [(JPEG, "jpg", "image/jpeg"), (PNG, "png", "image/png"), (WEBP, "webp", "image/webp")],
)
def test_reconhece_a_imagem_pelo_conteudo_e_nao_pelo_nome(dados, ext, tipo):
    assert sniff_image(dados) == (ext, tipo)


@pytest.mark.parametrize("dados", [b"", b"<html><script>alert(1)</script></html>", b"%PDF-1.7 ...", b"GIF89a....", b"\xff\xd8"])
def test_o_que_nao_e_imagem_aceita_e_recusado(dados):
    with pytest.raises(UploadError) as erro:
        sniff_image(dados)
    assert erro.value.status in (415, 422)


def test_guarda_e_devolve_com_chave_aleatoria(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    chave = loja.save("rider-1", "selfie", JPEG)
    assert chave.startswith("rider-1/selfie-") and chave.endswith(".jpg")
    assert loja.exists(chave) is True
    assert loja.read(chave) == (JPEG, "image/jpeg")
    assert loja.save("rider-1", "selfie", JPEG) != chave        # nunca sobrescreve


def test_arquivo_fica_so_para_o_dono_do_servidor(tmp_path):
    loja = LocalDocumentStore(tmp_path / "docs")
    chave = loja.save("rider-1", "cnh", PNG)
    arquivo = tmp_path / "docs" / chave
    assert stat.S_IMODE(os.stat(arquivo).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(arquivo.parent).st_mode) == 0o700


@pytest.mark.parametrize(
    "chave",
    ["../segredo", "rider-1/../../etc/passwd", "/etc/passwd", "rider-1/selfie-0123456789abcdef.exe", "rider-1/x", "", "a/b/c.jpg"],
)
def test_chave_estranha_nunca_chega_ao_disco(tmp_path, chave):
    loja = LocalDocumentStore(tmp_path)
    assert loja.exists(chave) is False
    with pytest.raises(LookupError):
        loja.read(chave)


def test_dono_e_tipo_invalidos_sao_recusados(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    with pytest.raises(ValueError):
        loja.save("../fora", "selfie", JPEG)
    with pytest.raises(ValueError):
        loja.save("rider-1", "senha", JPEG)
````

Crie `server/tests/services/test_riders_api.py`:

````python
import datetime as dt

import pytest

from app.db.models import RiderProfileRow
from app.infra.redis_store import InMemoryPositionStore
from app.services.events import EventCollector
from app.services.riders import DuplicateRegistration, RegistrationError, RiderService
from tests.services.test_riders import CPF2, HOJE, aprovado, cadastrar, novo_usuario


@pytest.fixture()
def service():
    return RiderService(InMemoryPositionStore(), EventCollector())


def test_cadastro_ao_mesmo_tempo_com_o_mesmo_cpf_vira_cadastro_repetido(service, session, monkeypatch):
    # Roteiro do 2B (menores): `register_rider` concorrente vazava `IntegrityError`.
    aprovado(service, session)
    novo_usuario(session, "r2", "+5575900000003")
    verdadeiro = RiderService._find_duplicate
    chamadas = []

    def cego_na_primeira(self, session, **dados):
        chamadas.append(1)
        return None if len(chamadas) == 1 else verdadeiro(self, session, **dados)

    monkeypatch.setattr(RiderService, "_find_duplicate", cego_na_primeira)
    with pytest.raises(DuplicateRegistration) as erro:
        cadastrar(service, session, "r2", cnh_number="99999999999", plate="ZZZ9Z99")
    assert erro.value.field == "CPF"
    assert session.get(RiderProfileRow, "r2") is None
    cadastrar(service, session, "r2", cpf=CPF2, cnh_number="99999999999", plate="ZZZ9Z99")   # a sessão segue usável
    assert session.get(RiderProfileRow, "r2") is not None


def test_enviar_o_cadastro_duas_vezes_ao_mesmo_tempo_nao_vaza_erro_do_banco(service, session, monkeypatch):
    novo_usuario(session)
    cadastrar(service, session)
    real_get = session.get
    cegas = []

    def get_cego_uma_vez(entidade, ident, *args, **kwargs):
        if entidade is RiderProfileRow and not cegas:
            cegas.append(1)
            return None
        return real_get(entidade, ident, *args, **kwargs)

    monkeypatch.setattr(session, "get", get_cego_uma_vez)
    monkeypatch.setattr(RiderService, "_find_duplicate", lambda self, session, **dados: None)
    with pytest.raises(RegistrationError, match="já foi enviado"):
        cadastrar(service, session)


def test_renovar_documentos_troca_as_fotos_so_quando_vierem_novas(service, session):
    aprovado(service, session)
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
        cnh_photo_key="nova-cnh.jpg",
    )
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.cnh_photo_key, perfil.crlv_key) == ("nova-cnh.jpg", "m.jpg")
    service.renew_documents(
        session, "r1", cnh_expires_on=dt.date(2032, 1, 1), crlv_expires_on=dt.date(2031, 1, 1), today=HOJE,
        crlv_key="novo-crlv.jpg",
    )
    perfil = session.get(RiderProfileRow, "r1")
    assert (perfil.cnh_photo_key, perfil.crlv_key) == ("nova-cnh.jpg", "novo-crlv.jpg")
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_rider_onboarding.py tests/infra/test_documents.py tests/services/test_riders_api.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.infra.documents'`.

- [ ] **Step 3: Implementar**

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -5,7 +5,10 @@ from fastapi import FastAPI
 from fastapi.responses import JSONResponse
 
 from app.api.errors import install_error_handlers
+from app.api.routes import admin as admin_routes
 from app.api.routes import auth as auth_routes
+from app.api.routes import files as files_routes
+from app.api.routes import rider as rider_routes
 
 
 def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
@@ -21,6 +24,9 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     app.state.runtime = runtime
     install_error_handlers(app)
     app.include_router(auth_routes.router)
+    app.include_router(rider_routes.router)
+    app.include_router(admin_routes.router)
+    app.include_router(files_routes.router)
 
     if runtime is not None:
 
````

Altere `server/app/api/errors.py`:

````diff
--- a/server/app/api/errors.py
+++ b/server/app/api/errors.py
@@ -14,6 +14,7 @@ from fastapi.responses import JSONResponse
 from starlette.exceptions import HTTPException as StarletteHTTPException
 
 from app.domain.payments import PaymentProviderError
+from app.infra.documents import UploadError
 from app.domain.rides import InvalidTransition
 from app.services.auth import TooManyRequests
 from app.services.dispatch import OfferGone
@@ -77,6 +78,10 @@ async def _cannot_go_online(request: Request, exc: CannotGoOnline) -> JSONRespon
     return error_response(409, exc.code, exc.message)
 
 
+async def _upload_error(request: Request, exc: UploadError) -> JSONResponse:
+    return error_response(exc.status, exc.code, exc.message)
+
+
 async def _duplicate_registration(request: Request, exc: DuplicateRegistration) -> JSONResponse:
     return error_response(409, "duplicate_registration", str(exc), field=exc.field)
 
@@ -112,6 +117,7 @@ def install_error_handlers(app: FastAPI) -> None:
         app.add_exception_handler(exc_class, _rule_handler(rule))
     app.add_exception_handler(ApiError, _api_error)
     app.add_exception_handler(CannotGoOnline, _cannot_go_online)
+    app.add_exception_handler(UploadError, _upload_error)
     app.add_exception_handler(DuplicateRegistration, _duplicate_registration)
     app.add_exception_handler(LookupError, _not_found)
     app.add_exception_handler(RequestValidationError, _validation)
````

Crie `server/app/api/routes/admin.py`:

````python
"""Rotas do administrador (o painel completo é o plano 4; aqui só o que o fluxo precisa para andar)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import admin_user, get_runtime
from app.db import queries
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/admin", tags=["administrador"])


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


def _rider_item(item: queries.RiderListItem) -> dict:
    return {
        "rider_id": item.rider_id, "name": item.name, "phone": item.phone, "cpf": item.cpf, "plate": item.plate,
        "moto_model": item.moto_model, "status": item.status, "reason": item.reason,
        "cnh_expires_on": item.cnh_expires_on.isoformat() if item.cnh_expires_on else None,
        "crlv_expires_on": item.crlv_expires_on.isoformat() if item.crlv_expires_on else None,
        "documents": list(item.documents),
    }


@router.get("/riders")
def list_riders(
    request: Request,
    status: Literal["pending", "approved", "blocked", "rejected"] = "pending",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: AuthUser = Depends(admin_user),
) -> list[dict]:
    items = get_runtime(request).run(lambda unit: queries.list_riders(unit.session, status, limit, offset))
    return [_rider_item(item) for item in items]


@router.post("/riders/{rider_id}/approve", status_code=204)
def approve(rider_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.approve(unit.session, rider_id, unit.now))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/reject", status_code=204)
def reject(rider_id: str, body: ReasonIn, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.reject(unit.session, rider_id, body.reason))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/block", status_code=204)
def block(rider_id: str, body: ReasonIn, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.block(unit.session, rider_id, body.reason))
    return Response(status_code=204)


@router.post("/riders/{rider_id}/unblock", status_code=204)
def unblock(rider_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
    get_runtime(request).run(lambda unit: unit.riders.unblock(unit.session, rider_id))
    return Response(status_code=204)
````

Crie `server/app/api/routes/files.py`:

````python
"""Ver a foto de um documento do motoqueiro. Nunca é um endereço público: sempre exige login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_user, get_runtime
from app.api.errors import ApiError
from app.api.routes.rider import DocKind
from app.db import queries
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1", tags=["documentos"])


@router.get("/riders/{rider_id}/documents/{kind}")
def get_document(rider_id: str, kind: DocKind, request: Request, user: AuthUser = Depends(current_user)) -> Response:
    """O administrador e o próprio motoqueiro veem tudo. O passageiro vê só a selfie, de quem já o buscou."""
    runtime = get_runtime(request)

    def work(unit):
        allowed = user.role == "admin" or user.user_id == rider_id or (
            user.role == "passenger" and kind == "selfie"
            and queries.passenger_rode_with(unit.session, user.user_id, rider_id)
        )
        if not allowed:
            raise ApiError(403, "forbidden", "Você não pode ver este documento.")
        key = queries.rider_document_key(unit.session, rider_id, kind)
        if key is None:
            raise LookupError(f"documento {kind} de {rider_id} não encontrado")
        return key

    data, media_type = runtime.documents.read(runtime.run(work))
    return Response(
        data, media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
````

Crie `server/app/api/routes/rider.py`:

````python
"""Rotas do motoqueiro: documentos e cadastro. (Disponibilidade e corridas entram na próxima tarefa.)"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, rider_user
from app.domain.clock import local_date
from app.infra.documents import KINDS, MAX_UPLOAD_BYTES, DocumentStore, UploadError
from app.services.auth import AuthUser, TooManyRequests
from app.services.riders import RegistrationError

router = APIRouter(prefix="/v1/rider", tags=["motoqueiro"])

DocKind = Literal["selfie", "cnh", "crlv"]
UPLOADS_PER_HOUR = 30
_KIND_NAMES = {"selfie": "o seu rosto (selfie)", "cnh": "a CNH", "crlv": "o documento da moto"}


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    cpf: str = Field(max_length=20)
    cnh_number: str = Field(max_length=20)
    plate: str = Field(max_length=10)
    moto_model: str = Field(min_length=1, max_length=80)
    selfie_key: str = Field(max_length=200)
    cnh_photo_key: str = Field(max_length=200)
    crlv_key: str = Field(max_length=200)
    cnh_expires_on: dt.date
    crlv_expires_on: dt.date


class RenewIn(BaseModel):
    cnh_expires_on: dt.date
    crlv_expires_on: dt.date
    cnh_photo_key: str | None = Field(default=None, max_length=200)
    crlv_key: str | None = Field(default=None, max_length=200)


def check_own_document(documents: DocumentStore, rider_id: str, kind: str, key: str) -> str:
    """A foto precisa ter sido enviada por este motoqueiro, ser do tipo certo e existir."""
    owner, _, name = key.partition("/")
    if owner != rider_id or not name.startswith(f"{kind}-") or not documents.exists(key):
        raise RegistrationError(f"Envie de novo a foto d{_KIND_NAMES[kind]}.")
    return key


def _save_upload(runtime, rider_id: str, kind: str, data: bytes) -> dict:
    if not runtime.limiter.hit(f"upload:{rider_id}", UPLOADS_PER_HOUR, 3600, runtime.clock()):
        raise TooManyRequests("Muitas fotos enviadas. Tente de novo mais tarde.")
    return {"key": runtime.documents.save(rider_id, kind, data), "bytes": len(data)}


@router.put("/documents/{kind}", status_code=201)
async def upload_document(kind: DocKind, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    """Recebe a foto crua no corpo do pedido (sem formulário). Corta em 8 MB mesmo sem tamanho declarado."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
        chunks.append(chunk)
    return await run_in_threadpool(_save_upload, get_runtime(request), user.user_id, kind, b"".join(chunks))


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
    runtime = get_runtime(request)
    keys = {
        "selfie": check_own_document(runtime.documents, user.user_id, "selfie", body.selfie_key),
        "cnh": check_own_document(runtime.documents, user.user_id, "cnh", body.cnh_photo_key),
        "crlv": check_own_document(runtime.documents, user.user_id, "crlv", body.crlv_key),
    }

    def work(unit):
        unit.riders.register_rider(
            unit.session, user.user_id, name=body.name, cpf=body.cpf, cnh_number=body.cnh_number, plate=body.plate,
            moto_model=body.moto_model, selfie_key=keys["selfie"], cnh_photo_key=keys["cnh"], crlv_key=keys["crlv"],
            cnh_expires_on=body.cnh_expires_on, crlv_expires_on=body.crlv_expires_on, today=local_date(unit.now),
        )

    runtime.run(work)
    return {"status": "pending"}


@router.post("/documents/renew", status_code=204)
def renew_documents(body: RenewIn, request: Request, user: AuthUser = Depends(rider_user)):
    runtime = get_runtime(request)
    cnh_key = check_own_document(runtime.documents, user.user_id, "cnh", body.cnh_photo_key) if body.cnh_photo_key else None
    crlv_key = check_own_document(runtime.documents, user.user_id, "crlv", body.crlv_key) if body.crlv_key else None
    runtime.run(
        lambda unit: unit.riders.renew_documents(
            unit.session, user.user_id, cnh_expires_on=body.cnh_expires_on, crlv_expires_on=body.crlv_expires_on,
            today=local_date(unit.now), cnh_photo_key=cnh_key, crlv_key=crlv_key,
        )
    )
    return Response(status_code=204)


assert set(DocKind.__args__) == set(KINDS)      # a lista da rota e a do armazenamento não podem divergir
````

Altere `server/app/db/queries.py`:

````diff
--- a/server/app/db/queries.py
+++ b/server/app/db/queries.py
@@ -260,4 +260,59 @@ def cash_rides_without_charge_ids(session: Session) -> list[str]:
             )
             .order_by(RideRow.id)
         ).scalars()
-    )
\ No newline at end of file
+    )
+
+
+@dataclass(frozen=True)
+class RiderListItem:
+    rider_id: str
+    name: str
+    phone: str
+    cpf: str
+    plate: str
+    moto_model: str
+    status: str
+    reason: str | None
+    cnh_expires_on: object
+    crlv_expires_on: object
+    documents: tuple[str, ...]          # quais fotos existem: selfie, cnh, crlv
+
+
+def list_riders(session: Session, status: str, limit: int, offset: int) -> list[RiderListItem]:
+    rows = session.execute(
+        select(RiderProfileRow, UserRow)
+        .join(UserRow, UserRow.id == RiderProfileRow.user_id)
+        .where(RiderProfileRow.status == status)
+        .order_by(UserRow.created_at, RiderProfileRow.user_id)
+        .limit(limit)
+        .offset(offset)
+    ).all()
+    return [
+        RiderListItem(
+            rider_id=p.user_id, name=u.name, phone=u.phone, cpf=p.cpf, plate=p.plate, moto_model=p.moto_model,
+            status=p.status, reason=p.rejected_reason, cnh_expires_on=p.cnh_expires_on,
+            crlv_expires_on=p.crlv_expires_on,
+            documents=tuple(
+                kind for kind, key in (("selfie", p.selfie_key), ("cnh", p.cnh_photo_key), ("crlv", p.crlv_key)) if key
+            ),
+        )
+        for p, u in rows
+    ]
+
+
+def rider_document_key(session: Session, rider_id: str, kind: str) -> str | None:
+    column = {"selfie": RiderProfileRow.selfie_key, "cnh": RiderProfileRow.cnh_photo_key, "crlv": RiderProfileRow.crlv_key}[kind]
+    return session.execute(select(column).where(RiderProfileRow.user_id == rider_id)).scalar_one_or_none()
+
+
+def passenger_rode_with(session: Session, passenger_id: str, rider_id: str) -> bool:
+    """O passageiro tem (ou teve) uma corrida aceita por este motoqueiro. Dá o direito de ver a selfie dele."""
+    return session.execute(
+        select(RideRow.id)
+        .where(
+            RideRow.passenger_id == passenger_id,
+            RideRow.rider_id == rider_id,
+            RideRow.state.notin_((RideState.CANCELLED.value, RideState.NO_RIDER.value)),
+        )
+        .limit(1)
+    ).first() is not None
````

Crie `server/app/infra/documents.py`:

````python
"""Fotos dos documentos do motoqueiro (selfie, CNH, documento da moto).

Ficam em disco, numa pasta fora do git, legíveis só pelo dono do servidor. A chave devolvida é
`<id do dono>/<tipo>-<16 letras e números aleatórios>.<ext>`: o tipo de arquivo vem do **conteúdo**
(não do nome que o celular mandou) e a chave nunca é montada a partir de texto livre.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Protocol

KINDS = ("selfie", "cnh", "crlv")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

_OWNER = re.compile(r"[A-Za-z0-9_-]{1,40}")
_KEY = re.compile(r"([A-Za-z0-9_-]{1,40})/(selfie|cnh|crlv)-[0-9a-f]{16}\.(jpg|png|webp)")
_MEDIA = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class UploadError(Exception):
    """Arquivo recusado. A mensagem é para o motoqueiro."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def sniff_image(data: bytes) -> tuple[str, str]:
    """Devolve (extensão, tipo de mídia) pelo começo do arquivo. Só JPEG, PNG e WebP."""
    if not data:
        raise UploadError(422, "empty_file", "O arquivo está vazio. Tire a foto de novo.")
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", _MEDIA["jpg"]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", _MEDIA["png"]
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", _MEDIA["webp"]
    raise UploadError(415, "not_an_image", "Envie uma foto (JPEG, PNG ou WebP).")


class DocumentStore(Protocol):
    def save(self, owner_id: str, kind: str, data: bytes) -> str: ...

    def read(self, key: str) -> tuple[bytes, str]: ...

    def exists(self, key: str) -> bool: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path | None:
        match = _KEY.fullmatch(key)
        return self.root / match.group(1) / key.split("/", 1)[1] if match else None

    def save(self, owner_id: str, kind: str, data: bytes) -> str:
        if not _OWNER.fullmatch(owner_id):
            raise ValueError("dono inválido")
        if kind not in KINDS:
            raise ValueError("tipo de documento inválido")
        ext, _ = sniff_image(data)
        key = f"{owner_id}/{kind}-{secrets.token_hex(8)}.{ext}"
        path = self._path(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        temp = path.with_suffix(path.suffix + ".part")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)           # aparece inteiro ou não aparece
        return key

    def exists(self, key: str) -> bool:
        path = self._path(key)
        return path is not None and path.is_file()

    def read(self, key: str) -> tuple[bytes, str]:
        path = self._path(key)
        if path is None or not path.is_file():
            raise LookupError(f"documento {key} não encontrado")
        return path.read_bytes(), _MEDIA[path.suffix[1:]]
````

Altere `server/app/runtime.py`:

````diff
--- a/server/app/runtime.py
+++ b/server/app/runtime.py
@@ -25,6 +25,7 @@ from app.db.config_store import AppConfig, load_app_config
 from app.db.session import make_engine, make_session_factory
 from app.domain.maps import MapsProvider
 from app.domain.payments import PaymentProvider
+from app.infra.documents import DocumentStore, LocalDocumentStore
 from app.infra.redis_store import (
     FactorStore,
     JobMarks,
@@ -88,6 +89,7 @@ class Runtime:
     limiter: RateLimiter
     pix_health: PixHealth
     job_marks: JobMarks
+    documents: DocumentStore
     mode: str = "production"
     clock: Callable[[], float] = time.time
     redis_client: Any = None
@@ -179,6 +181,7 @@ def build_runtime(settings: Settings) -> Runtime:
         limiter=RedisRateLimiter(client),
         pix_health=RedisPixHealth(client),
         job_marks=RedisJobMarks(client),
+        documents=LocalDocumentStore(settings.upload_dir),
         mode="dev",
         redis_client=client,
     )
````

Altere `server/app/services/riders.py`:

````diff
--- a/server/app/services/riders.py
+++ b/server/app/services/riders.py
@@ -5,6 +5,7 @@ import datetime as dt
 import re
 
 from sqlalchemy import select
+from sqlalchemy.exc import IntegrityError
 from sqlalchemy.orm import Session
 
 from app.db import queries
@@ -107,22 +108,38 @@ class RiderService:
             raise RegistrationError("Sua CNH está vencida.")
         if crlv_expires_on < today:
             raise RegistrationError("O documento da moto está vencido.")
+        duplicate = self._find_duplicate(session, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok)
+        if duplicate is not None:
+            raise duplicate
+        user.name = clean_name
+        try:
+            with session.begin_nested():
+                session.add(
+                    RiderProfileRow(
+                        user_id=user_id, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok,
+                        moto_model=moto_model.strip(), status="pending", selfie_key=selfie_key,
+                        cnh_photo_key=cnh_photo_key, crlv_key=crlv_key,
+                        cnh_expires_on=cnh_expires_on, crlv_expires_on=crlv_expires_on,
+                    )
+                )
+                session.flush()
+        except IntegrityError:
+            # Outro cadastro entrou entre a conferência e a gravação (dois toques, duas telas): o banco decide.
+            raise self._find_duplicate(
+                session, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok
+            ) or RegistrationError("Seu cadastro já foi enviado.") from None
+
+    def _find_duplicate(
+        self, session: Session, *, cpf: str, cnh_number: str, plate: str
+    ) -> DuplicateRegistration | None:
         for field, phrase, column, value in (
-            ("CPF", "este CPF", RiderProfileRow.cpf, cpf_ok),
-            ("número de CNH", "este número de CNH", RiderProfileRow.cnh_number, cnh_ok),
-            ("placa", "esta placa", RiderProfileRow.plate, plate_ok),
+            ("CPF", "este CPF", RiderProfileRow.cpf, cpf),
+            ("número de CNH", "este número de CNH", RiderProfileRow.cnh_number, cnh_number),
+            ("placa", "esta placa", RiderProfileRow.plate, plate),
         ):
             if session.execute(select(RiderProfileRow.user_id).where(column == value)).first() is not None:
-                raise DuplicateRegistration(field, phrase)
-        user.name = clean_name
-        session.add(
-            RiderProfileRow(
-                user_id=user_id, cpf=cpf_ok, cnh_number=cnh_ok, plate=plate_ok, moto_model=moto_model.strip(),
-                status="pending", selfie_key=selfie_key, cnh_photo_key=cnh_photo_key, crlv_key=crlv_key,
-                cnh_expires_on=cnh_expires_on, crlv_expires_on=crlv_expires_on,
-            )
-        )
-        session.flush()
+                return DuplicateRegistration(field, phrase)
+        return None
 
     def _profile(self, session: Session, rider_id: str) -> RiderProfileRow:
         row = session.execute(
@@ -171,13 +188,25 @@ class RiderService:
         self.events.add(rider_id, "rider_unblocked")
 
     def renew_documents(
-        self, session: Session, rider_id: str, *, cnh_expires_on: dt.date, crlv_expires_on: dt.date, today: dt.date
+        self,
+        session: Session,
+        rider_id: str,
+        *,
+        cnh_expires_on: dt.date,
+        crlv_expires_on: dt.date,
+        today: dt.date,
+        cnh_photo_key: str | None = None,
+        crlv_key: str | None = None,
     ) -> None:
         if cnh_expires_on < today or crlv_expires_on < today:
             raise RegistrationError("As novas datas já estão vencidas.")
         profile = self._profile(session, rider_id)
         profile.cnh_expires_on = cnh_expires_on
         profile.crlv_expires_on = crlv_expires_on
+        if cnh_photo_key is not None:
+            profile.cnh_photo_key = cnh_photo_key
+        if crlv_key is not None:
+            profile.crlv_key = crlv_key
         session.flush()
 
     # --- disponibilidade ----------------------------------------------------------
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_rider_onboarding.py tests/infra/test_documents.py tests/services/test_riders_api.py`
Expected: `44 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `520 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): fotos dos documentos, cadastro e aprovação do motoqueiro" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 7: Passageiro: preço, pedido, cancelamento, avaliação, contato de emergência e estado

O passageiro pelo celular: preço (com o tempo de chegada estimado e as formas de pagar), pedido, cancelamento, avaliação, contato de emergência e o **estado** que o app pede ao abrir ou reconectar. A cotação passa a guardar a rota do mapa, a corrida herda essa rota, e trajeto curto demais ou longe demais é recusado.

**Files:**
- Modify: `server/app/api/app.py`
- Create: `server/app/api/routes/passenger.py`
- Create: `server/app/api/routes/rides.py`
- Create: `server/app/api/schemas.py`
- Create: `server/app/api/views.py`
- Modify: `server/app/runtime.py`
- Modify: `server/app/services/quotes.py`
- Modify: `server/app/services/ride_requests.py`
- Test: `server/tests/api/helpers.py` (alterado)
- Test: `server/tests/api/test_passenger_routes.py` (novo)
- Test: `server/tests/services/test_quotes_api.py` (novo)
- Test: `server/tests/services/test_ride_requests_api.py` (novo)

**Interfaces:**
- Consumes: `QuoteService`, `RideRequestService`, `TripService.cancel_by_passenger/rate`, `repo.get_emergency_contact`, `Runtime.pix_health`.
- Produces: `Quote.eta_seconds`, `Quote.nearby_riders`, `Quote.route`; `Runtime.payment_methods(now) -> list[str]`; `Unit.positions`; `app.api.schemas.PlaceIn` (`.point`) e `StarsIn`; `app.api.views`: `place`, `quote_view`, `passenger_ride_view(unit, ride_id)`, `passenger_state(unit, passenger_id, payment_methods)`; rotas `/v1/passenger/quotes`, `/v1/passenger/rides`, `/v1/passenger/rides/{id}/cancel`, `/v1/passenger/state`, `/v1/passenger/emergency-contact`, `/v1/rides/{id}/rating`. Ajudantes de teste `online_rider(session, runtime, clock, n=1, point=None) -> rider_id` e `rider_phone(n)`.

- [ ] **Step 1: Escrever os testes que falham**

Altere `server/tests/api/helpers.py`:

````diff
--- a/server/tests/api/helpers.py
+++ b/server/tests/api/helpers.py
@@ -27,3 +27,16 @@ def login(client, runtime, phone: str, role: str, name: str | None = None) -> Lo
     if name:
         assert client.put("/v1/me", json={"name": name}, headers=entrou.headers).status_code == 200
     return entrou
+
+
+def rider_phone(n: int) -> str:
+    """Celular do motoqueiro que `online_rider(n)` cria (já no formato que o login aceita)."""
+    return f"75977{n:06d}"
+
+
+def online_rider(session, runtime, clock, n: int = 1, point=None) -> str:
+    """Motoqueiro aprovado, disponível e com posição fresca. Devolve o id; entra na API com `rider_phone(n)`."""
+    from tests.helpers import pt
+    from tests.helpers_db import make_online_rider
+
+    return make_online_rider(session, runtime.positions, n, point or pt(300, 0), now=clock.now)
````

Crie `server/tests/api/test_passenger_routes.py`:

````python
import pytest

from app.db import repositories as repo
from app.db.models import QuoteRow, RiderProfileRow
from app.domain.types import PaymentMethod
from tests.api.helpers import login, online_rider
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_completed_ride


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


def cotar(client, quem, corpo=QUOTE):
    resposta = client.post("/v1/passenger/quotes", json=corpo, headers=quem.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def pedir(client, quem, quote_id, metodo="pix"):
    return client.post("/v1/passenger/rides", json={"quote_id": quote_id, "method": metodo}, headers=quem.headers)


# --- preço -----------------------------------------------------------------------------------


def test_cotacao_mostra_preco_motivo_chegada_e_formas_de_pagar(client, pax, session, runtime, clock):
    online_rider(session, runtime, clock)
    corpo = cotar(client, pax)
    assert corpo["price_cents"] == 550 and corpo["reason"] == "Muita moto livre agora, preço menor."   # 1 moto, 0 pedidos
    assert corpo["payment_methods"] == ["pix", "cash"]
    assert corpo["nearby_riders"] == 1 and 40 <= corpo["eta_seconds"] <= 70
    assert corpo["pickup"] == lugar(ORIGIN, "Rua A") | {"lat": ORIGIN.lat, "lng": ORIGIN.lng}
    assert corpo["expires_at"] == clock.now + 300
    assert session.get(QuoteRow, corpo["quote_id"]).passenger_id == pax.user_id


def test_sem_motos_a_cotacao_sai_sem_tempo_de_chegada(client, pax):
    corpo = cotar(client, pax)
    assert corpo["eta_seconds"] is None and corpo["nearby_riders"] == 0


@pytest.mark.parametrize(
    "mudar, status",
    [
        ({"pickup": lugar(ORIGIN, "A") | {"lat": 91}}, 422),
        ({"destination": lugar(ORIGIN, "A") | {"lng": -181}}, 422),
        ({"destination": lugar(ORIGIN, "A") | {"lat": "norte"}}, 422),
        ({"pickup": lugar(ORIGIN, "x" * 201)}, 422),
        ({"destination": lugar(ORIGIN, "mesmo lugar")}, 403),
        ({"destination": lugar(pt(80_000, 0), "outra cidade")}, 403),
    ],
)
def test_cotacao_com_lugar_invalido_ou_trajeto_absurdo_e_recusada(client, pax, mudar, status):
    resposta = client.post("/v1/passenger/quotes", json=QUOTE | mudar, headers=pax.headers)
    assert resposta.status_code == status


def test_pix_fora_do_ar_oferece_so_dinheiro_e_recusa_pedido_em_pix(client, pax, runtime, clock):
    runtime.pix_health.mark_down(clock.now, for_s=60)
    corpo = cotar(client, pax)
    assert corpo["payment_methods"] == ["cash"]
    resposta = pedir(client, pax, corpo["quote_id"], "pix")
    assert resposta.status_code == 403 and "Pix" in resposta.json()["error"]["message"]
    assert pedir(client, pax, corpo["quote_id"], "cash").status_code == 201      # a cotação não foi gasta
    clock.advance(61)
    assert cotar(client, login(client, runtime, "75 99999-0007", "passenger"))["payment_methods"] == ["pix", "cash"]


# --- pedido ----------------------------------------------------------------------------------


def test_pedido_procura_moto_e_so_depois_do_commit_o_motoqueiro_recebe_a_oferta(
    client, pax, session, runtime, clock, listen
):
    rider_id = online_rider(session, runtime, clock)
    avisos = listen(rider_id)
    resposta = pedir(client, pax, cotar(client, pax)["quote_id"])
    assert resposta.status_code == 201
    corrida = resposta.json()
    assert corrida["state"] == "searching" and corrida["method"] == "pix" and corrida["price_cents"] == 550
    assert len(corrida["pin"]) == 4 and corrida["rider"] is None and corrida["pay"] is None
    assert corrida["pickup"]["text"] == "Rua A" and corrida["destination"]["text"] == "Feira livre"
    assert avisos.types == ["offer"]
    assert avisos.messages[0]["data"]["ride_id"] == corrida["ride_id"]
    assert avisos.messages[0]["data"]["price_cents"] == 550


def test_pedido_sem_moto_fica_procurando(client, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"], "cash").json()
    assert corrida["state"] == "searching" and corrida["method"] == "cash"


def test_so_uma_corrida_por_vez_e_cotacao_de_outro_nao_vale(client, runtime, pax):
    primeira, segunda = cotar(client, pax), cotar(client, pax)
    assert pedir(client, pax, primeira["quote_id"]).status_code == 201
    resposta = pedir(client, pax, segunda["quote_id"])
    assert resposta.status_code == 403 and "já tem uma corrida" in resposta.json()["error"]["message"]
    outro = login(client, runtime, "75 99999-0005", "passenger")
    resposta = pedir(client, outro, primeira["quote_id"])
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "quote_expired"
    assert pedir(client, pax, "q-inventada").status_code == 409


def test_forma_de_pagar_invalida_e_422(client, pax):
    resposta = client.post("/v1/passenger/rides", json={"quote_id": "q-1", "method": "cartao"}, headers=pax.headers)
    assert resposta.status_code == 422


def test_cancelar_retira_a_oferta_do_motoqueiro_e_libera_o_passageiro(client, pax, session, runtime, clock, listen):
    rider_id = online_rider(session, runtime, clock)
    avisos = listen(rider_id)
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    resposta = client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers)
    assert resposta.status_code == 200 and resposta.json() == {"refund": False}
    assert avisos.types == ["offer", "offer_expired"]
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None
    assert pedir(client, pax, cotar(client, pax)["quote_id"]).status_code == 201


def test_cancelar_corrida_dos_outros_ou_inexistente(client, runtime, pax):
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    outro = login(client, runtime, "75 99999-0005", "passenger")
    resposta = client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=outro.headers)
    assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "not_your_ride"
    assert client.post("/v1/passenger/rides/nao-existe/cancel", headers=pax.headers).status_code == 404


# --- estado (o que o app pede ao abrir ou reconectar) --------------------------------------------


def test_estado_do_passageiro_sem_corrida(client, pax):
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado == {
        "ride": None, "pending_payment": None, "blocked_reason": None, "unpaid_cents": 0,
        "emergency_contact": None, "payment_methods": ["pix", "cash"],
    }


def test_estado_com_motoqueiro_a_caminho_traz_ficha_codigo_pix_e_posicao(
    client, pax, session, runtime, clock
):
    rider_id = online_rider(session, runtime, clock)
    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    runtime.run(lambda u: u.dispatch.accept_offer(u.session, rider_id, corrida["ride_id"], u.now))
    ride = client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]
    assert ride["state"] == "accepted" and ride["pin"] == corrida["pin"] and ride["queued"] is False
    assert ride["rider"]["name"] == f"Motoqueiro {rider_id}" and ride["rider"]["plate"] == "ABC0001"
    assert ride["rider"]["photo_url"] is None and ride["rider"]["rating"] is None
    assert ride["pay"]["amount_cents"] == 550 and ride["pay"]["expires_at"] == clock.now + 120
    assert ride["pay"]["charge_id"] == repo.get_current_charge_id(session, corrida["ride_id"])
    assert ride["rider_position"] == pytest.approx({"lat": pt(300, 0).lat, "lng": pt(300, 0).lng}, abs=1e-5)


def test_estado_mostra_pagamento_pendente_e_bloqueio_de_quem_nao_pagou(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.CASH, price=700, fee=100)
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado["pending_payment"] == {
        "ride_id": "ride-9", "amount_cents": 700, "charge_id": None, "blocked": False,
    }
    assert estado["blocked_reason"] and "Falta pagar" in estado["blocked_reason"]


# --- contato de emergência ------------------------------------------------------------------------


def test_contato_de_emergencia_guarda_o_numero_normalizado(client, pax):
    corpo = {"name": "Maria", "phone": "(75) 98888-7777"}
    assert client.put("/v1/passenger/emergency-contact", json=corpo, headers=pax.headers).status_code == 204
    estado = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado["emergency_contact"] == {"name": "Maria", "phone": "+5575988887777"}


@pytest.mark.parametrize(
    "corpo",
    [{"name": "Eu mesmo", "phone": "75 99999-0001"}, {"name": "Maria", "phone": "123"}, {"name": "", "phone": "75 98888-7777"}],
)
def test_contato_de_emergencia_invalido_e_recusado(client, pax, corpo):
    assert client.put("/v1/passenger/emergency-contact", json=corpo, headers=pax.headers).status_code == 422


# --- avaliação ----------------------------------------------------------------------------------------


def test_avaliar_o_motoqueiro_uma_vez_so_e_atualiza_a_nota(client, pax, session, runtime, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX)
    resposta = client.post("/v1/rides/ride-9/rating", json={"stars": 5}, headers=pax.headers)
    assert resposta.status_code == 204
    assert session.get(RiderProfileRow, rider_id).rating_count == 1
    segunda = client.post("/v1/rides/ride-9/rating", json={"stars": 1}, headers=pax.headers)
    assert segunda.status_code == 409 and segunda.json()["error"]["code"] == "already_rated"


@pytest.mark.parametrize("estrelas", [0, 6, -1, "cinco", None])
def test_nota_fora_de_1_a_5_e_422(client, pax, estrelas):
    assert client.post("/v1/rides/ride-9/rating", json={"stars": estrelas}, headers=pax.headers).status_code == 422


def test_so_quem_participou_avalia_e_so_corrida_terminada(client, runtime, pax, session, clock):
    rider_id = online_rider(session, runtime, clock)
    add_completed_ride(session, "ride-9", pax.user_id, rider_id, PaymentMethod.PIX)
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    resposta = client.post("/v1/rides/ride-9/rating", json={"stars": 5}, headers=intruso.headers)
    assert resposta.status_code == 403
    assert client.post("/v1/rides/nao-existe/rating", json={"stars": 5}, headers=pax.headers).status_code == 404
    aberta = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
    resposta = client.post(f"/v1/rides/{aberta['ride_id']}/rating", json={"stars": 5}, headers=pax.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"


def test_rotas_do_passageiro_sao_so_do_passageiro(client, runtime):
    motoqueiro = login(client, runtime, "75 99999-0002", "rider")
    for metodo, url in (
        ("post", "/v1/passenger/quotes"), ("post", "/v1/passenger/rides"), ("get", "/v1/passenger/state"),
        ("put", "/v1/passenger/emergency-contact"),
    ):
        assert getattr(client, metodo)(url, headers=motoqueiro.headers).status_code == 403
        assert getattr(client, metodo)(url).status_code == 401
````

Crie `server/tests/services/test_quotes_api.py`:

````python
import pytest
from sqlalchemy import select

from app.adapters.fake_maps import FakeMaps
from app.db.models import QuoteRow
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.quotes import NotAllowed, QuoteService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_accepted_ride, add_passenger, make_online_rider


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def service(positions):
    return QuoteService(FakeMaps(), positions, InMemoryFactorStore())


def cotar(service, session, destino=pt(1500, 0), now=1000.0):
    return service.create_quote(session, "p1", ORIGIN, destino, "Rua A", "Feira livre", now)


def test_cotacao_guarda_a_rota_do_mapa_para_o_aviso_de_saida_da_rota(service, session):
    add_passenger(session)
    quote = cotar(service, session)
    assert quote.route == ((ORIGIN.lat, ORIGIN.lng), (pt(1500, 0).lat, pt(1500, 0).lng))
    assert session.execute(select(QuoteRow.route)).scalar_one() == [list(p) for p in quote.route]


@pytest.mark.parametrize("destino, trecho", [(ORIGIN, "perto"), (pt(30, 0), "perto"), (pt(50_000, 0), "longe")])
def test_trajeto_curto_demais_ou_longo_demais_e_recusado(service, session, destino, trecho):
    add_passenger(session)
    with pytest.raises(NotAllowed, match=trecho):
        cotar(service, session, destino)
    assert session.execute(select(QuoteRow)).first() is None


def test_tempo_de_chegada_estimado_vem_da_moto_livre_mais_proxima(service, session, positions):
    add_passenger(session)
    sem_motos = cotar(service, session)
    assert sem_motos.eta_seconds is None and sem_motos.nearby_riders == 0
    make_online_rider(session, positions, 1, pt(700, 0), now=1000.0)
    make_online_rider(session, positions, 2, pt(300, 0), now=1000.0)
    com_motos = cotar(service, session)
    assert com_motos.nearby_riders == 2
    assert com_motos.eta_seconds == pytest.approx(300 * 1.3 / 7.0, abs=3)      # a mais perto, em linha reta x 1,3 a 25 km/h


def test_moto_ocupada_nao_entra_na_estimativa(service, session, positions):
    add_passenger(session)
    add_passenger(session, "p2", "+5575900000010")
    ocupada = make_online_rider(session, positions, 1, pt(100, 0), now=1000.0)
    livre = make_online_rider(session, positions, 2, pt(900, 0), now=1000.0)
    add_accepted_ride(session, ride_id="ride-9", passenger_id="p2", rider_id=ocupada)
    quote = cotar(service, session)
    assert quote.nearby_riders == 1
    assert quote.eta_seconds == pytest.approx(900 * 1.3 / 7.0, abs=3)
    assert livre
````

Crie `server/tests/services/test_ride_requests_api.py`:

````python
import pytest
from sqlalchemy import func, select

from app.adapters.fake_maps import FakeMaps
from app.db import repositories as repo
from app.db.models import QuoteRow, RideRow
from app.domain.types import PaymentMethod
from app.infra.redis_store import InMemoryFactorStore, InMemoryPositionStore
from app.services.events import EventCollector
from app.services.quotes import NotAllowed, QuoteService
from app.services.ride_requests import RideRequestService
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_passenger


@pytest.fixture()
def quotes():
    return QuoteService(FakeMaps(), InMemoryPositionStore(), InMemoryFactorStore())


@pytest.fixture()
def requests():
    return RideRequestService(None, EventCollector())


def cotar(quotes, session, now=1000.0):
    return quotes.create_quote(session, "p1", ORIGIN, pt(1500, 0), "Rua A", "Feira livre", now)


def test_a_corrida_herda_a_rota_do_preco_mostrado(quotes, requests, session):
    add_passenger(session)
    quote = cotar(quotes, session)
    ride = requests.request_ride(session, "p1", quote.quote_id, PaymentMethod.CASH, now=1010.0)
    assert repo.get_ride_details(session, ride.ride_id).route == quote.route


def test_se_a_conferencia_falhar_o_indice_do_banco_ainda_impede_a_segunda_corrida(
    quotes, requests, session, monkeypatch
):
    add_passenger(session)
    primeira, segunda = cotar(quotes, session), cotar(quotes, session)
    requests.request_ride(session, "p1", primeira.quote_id, PaymentMethod.CASH, now=1010.0)
    monkeypatch.setattr("app.services.ride_requests.passenger_block_reason", lambda session, passenger_id: None)
    with pytest.raises(NotAllowed, match="já tem uma corrida"):
        requests.request_ride(session, "p1", segunda.quote_id, PaymentMethod.CASH, now=1011.0)
    assert session.execute(select(func.count()).select_from(RideRow)).scalar_one() == 1
    assert session.get(QuoteRow, segunda.quote_id).used is False       # a cotação não foi gasta
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_passenger_routes.py tests/services/test_quotes_api.py tests/services/test_ride_requests_api.py`
Expected: FAIL — `38 failed` (primeiro erro: `AssertionError: {"error":{"code":"http_404","message":"Não encontramos o que você procura."}}`).

- [ ] **Step 3: Implementar**

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -8,7 +8,9 @@ from app.api.errors import install_error_handlers
 from app.api.routes import admin as admin_routes
 from app.api.routes import auth as auth_routes
 from app.api.routes import files as files_routes
+from app.api.routes import passenger as passenger_routes
 from app.api.routes import rider as rider_routes
+from app.api.routes import rides as rides_routes
 
 
 def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
@@ -27,6 +29,8 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     app.include_router(rider_routes.router)
     app.include_router(admin_routes.router)
     app.include_router(files_routes.router)
+    app.include_router(passenger_routes.router)
+    app.include_router(rides_routes.router)
 
     if runtime is not None:
 
````

Crie `server/app/api/routes/passenger.py`:

````python
"""Rotas do passageiro: preço, pedido, cancelamento, contato de emergência e estado."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, passenger_user
from app.api.schemas import PlaceIn
from app.api.views import passenger_ride_view, passenger_state, quote_view
from app.db import repositories as repo
from app.domain.types import PaymentMethod
from app.services.auth import AuthUser, normalize_phone
from app.services.quotes import NotAllowed

router = APIRouter(prefix="/v1/passenger", tags=["passageiro"])


class QuoteIn(BaseModel):
    pickup: PlaceIn
    destination: PlaceIn


class RideIn(BaseModel):
    quote_id: str = Field(min_length=1, max_length=40)
    method: Literal["pix", "cash"]


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)


@router.post("/quotes")
def create_quote(body: QuoteIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)

    def work(unit):
        quote = unit.quotes.create_quote(
            unit.session, user.user_id, body.pickup.point, body.destination.point,
            body.pickup.text, body.destination.text, unit.now,
        )
        return quote_view(quote, runtime.payment_methods(unit.now))

    return runtime.run(work)


@router.post("/rides", status_code=201)
def request_ride(body: RideIn, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)

    def work(unit):
        method = PaymentMethod(body.method)
        if method is PaymentMethod.PIX and runtime.pix_health.is_down(unit.now):
            raise NotAllowed("O Pix está fora do ar agora. Escolha pagar em dinheiro.")
        ride = unit.requests.request_ride(unit.session, user.user_id, body.quote_id, method, unit.now)
        return passenger_ride_view(unit, ride.ride_id)

    return runtime.run(work)


@router.post("/rides/{ride_id}/cancel")
def cancel_ride(ride_id: str, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    result = get_runtime(request).run(
        lambda unit: unit.trips.cancel_by_passenger(unit.session, user.user_id, ride_id, unit.now)
    )
    # A compensação do cancelamento tardio ainda não é cobrada (política em aberto): não é prometida ao app.
    return {"refund": result.refund_needed}


@router.get("/state")
def state(request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    runtime = get_runtime(request)
    return runtime.run(lambda unit: passenger_state(unit, user.user_id, runtime.payment_methods(unit.now)))


@router.put("/emergency-contact", status_code=204)
def set_emergency_contact(body: ContactIn, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    phone = normalize_phone(body.phone)
    if phone == user.phone:
        raise ValueError("Use o número de outra pessoa, que possa te ajudar.")
    get_runtime(request).run(
        lambda unit: repo.set_emergency_contact(unit.session, user.user_id, body.name.strip(), phone)
    )
    return Response(status_code=204)
````

Crie `server/app/api/routes/rides.py`:

````python
"""Rotas que os dois lados usam na mesma corrida."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_runtime, require_role
from app.api.schemas import StarsIn
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/rides", tags=["corrida"])


@router.post("/{ride_id}/rating", status_code=204)
def rate(
    ride_id: str, body: StarsIn, request: Request, user: AuthUser = Depends(require_role("passenger", "rider"))
) -> Response:
    get_runtime(request).run(lambda unit: unit.trips.rate(unit.session, user.user_id, ride_id, body.stars, unit.now))
    return Response(status_code=204)
````

Crie `server/app/api/schemas.py`:

````python
"""Corpos de pedido que mais de uma rota usa."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.geo import GeoPoint


class PlaceIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    text: str = Field(default="", max_length=200)

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(self.lat, self.lng)


class StarsIn(BaseModel):
    stars: int = Field(ge=1, le=5)
````

Crie `server/app/api/views.py`:

````python
"""Como a corrida aparece para cada lado. Só monta dicionários a partir do banco; não decide nada."""
from __future__ import annotations

from app.db import queries
from app.db import repositories as repo
from app.domain.rides import Ride, RideState
from app.domain.types import PaymentMethod
from app.runtime import Unit
from app.services.quotes import Quote, passenger_block_reason

_WITH_RIDER_ON_THE_MOVE = (RideState.ACCEPTED, RideState.ARRIVED, RideState.IN_PROGRESS)


def place(lat: float, lng: float, text: str) -> dict:
    return {"lat": lat, "lng": lng, "text": text}


def quote_view(quote: Quote, payment_methods: list[str]) -> dict:
    return {
        "quote_id": quote.quote_id, "price_cents": quote.price_cents, "distance_m": quote.distance_m,
        "duration_s": quote.duration_s, "reason": quote.reason, "expires_at": quote.expires_at,
        "pickup": place(quote.pickup.lat, quote.pickup.lng, quote.pickup_text),
        "destination": place(quote.destination.lat, quote.destination.lng, quote.destination_text),
        "eta_seconds": quote.eta_seconds, "nearby_riders": quote.nearby_riders,
        "payment_methods": payment_methods,
    }


def _pix_to_pay(unit: Unit, ride: Ride) -> dict | None:
    """Pix de antes da corrida que o passageiro ainda não pagou: o que ele precisa para pagar."""
    if ride.payment_method is not PaymentMethod.PIX or ride.pix_paid or ride.pix_charge_created_at is None:
        return None
    if ride.state not in (RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED):
        return None
    charge_id = repo.get_current_charge_id(unit.session, ride.ride_id)
    if charge_id is None:
        return None
    return {
        "charge_id": charge_id, "amount_cents": repo.get_charge(unit.session, charge_id).amount_cents,
        "expires_at": ride.pix_charge_created_at + unit.cfg.rides.pix_window_s,
    }


def _end_payment(unit: Unit, ride: Ride) -> dict | None:
    """Corrida em dinheiro já terminada e ainda sem pagamento confirmado (QR do fim da corrida)."""
    if ride.state is not RideState.COMPLETED or ride.payment_method is not PaymentMethod.CASH:
        return None
    if ride.end_payment_confirmed:
        return None
    return {
        "charge_id": repo.get_current_charge_id(unit.session, ride.ride_id),
        "amount_cents": ride.price_cents, "blocked": ride.non_payment_reported,
    }


def passenger_ride_view(unit: Unit, ride_id: str) -> dict:
    ride = repo.get_ride(unit.session, ride_id)
    details = repo.get_ride_details(unit.session, ride_id)
    rider = None
    position = None
    if ride.rider_id is not None:
        card = queries.rider_card(unit.session, ride.rider_id)
        rider = {
            "rider_id": card.rider_id, "name": card.name, "plate": card.plate, "moto_model": card.moto_model,
            "rating": card.rating, "rating_count": card.rating_count,
            "photo_url": f"/v1/riders/{card.rider_id}/documents/selfie" if card.selfie_key else None,
        }
        if ride.state in _WITH_RIDER_ON_THE_MOVE:
            found = unit.positions.get(ride.rider_id)
            position = None if found is None else {"lat": found.lat, "lng": found.lng}
    return {
        "ride_id": ride.ride_id, "state": ride.state.value, "queued": ride.state is RideState.QUEUED,
        "price_cents": ride.price_cents, "price_reason": details.price_reason, "method": ride.payment_method.value,
        "pin": ride.pin, "helmet_confirmed": ride.helmet_confirmed, "pix_paid": ride.pix_paid,
        "pickup": place(details.pickup.lat, details.pickup.lng, details.pickup_text),
        "destination": place(details.destination.lat, details.destination.lng, details.destination_text),
        "distance_m": details.distance_m, "rider": rider, "rider_position": position,
        "pay": _pix_to_pay(unit, ride), "end_payment": _end_payment(unit, ride),
    }


def passenger_state(unit: Unit, passenger_id: str, payment_methods: list[str]) -> dict:
    session = unit.session
    open_id = queries.passenger_open_ride_id(session, passenger_id)
    unpaid_id = queries.passenger_unpaid_cash_ride_id(session, passenger_id)
    pending = None
    if unpaid_id is not None:
        unpaid = repo.get_ride(session, unpaid_id)
        pending = {
            "ride_id": unpaid_id, "amount_cents": unpaid.price_cents,
            "charge_id": repo.get_current_charge_id(session, unpaid_id), "blocked": unpaid.non_payment_reported,
        }
    contact = repo.get_emergency_contact(session, passenger_id)
    return {
        "ride": passenger_ride_view(unit, open_id) if open_id else None,
        "pending_payment": pending,
        "blocked_reason": None if open_id else passenger_block_reason(session, passenger_id),
        "unpaid_cents": repo.get_passenger_account(session, passenger_id).unpaid_cents,
        "emergency_contact": None if contact is None else {"name": contact.name, "phone": contact.phone},
        "payment_methods": payment_methods,
    }
````

Altere `server/app/runtime.py`:

````diff
--- a/server/app/runtime.py
+++ b/server/app/runtime.py
@@ -66,6 +66,7 @@ class Unit:
     now: float
     cfg: AppConfig
     events: EventCollector
+    positions: PositionStore
     auth: AuthService
     riders: RiderService
     payments: PaymentService
@@ -106,6 +107,10 @@ class Runtime:
             self._config = (now, load_app_config(session))
         return self._config[1]
 
+    def payment_methods(self, now: float) -> list[str]:
+        """O que o passageiro pode escolher agora. Com o Pix fora do ar, só dinheiro (spec, seção 12)."""
+        return ["cash"] if self.pix_health.is_down(now) else ["pix", "cash"]
+
     # --- unidade de trabalho --------------------------------------------------------------------
 
     def make_unit(self, session: Session) -> Unit:
@@ -115,7 +120,7 @@ class Runtime:
         dispatch = DispatchService(self.positions, self.reservations, self.maps, payments, events, cfg)
         trips = TripService(payments, dispatch, events, cfg)
         return Unit(
-            session=session, now=self.clock(), cfg=cfg, events=events,
+            session=session, now=self.clock(), cfg=cfg, events=events, positions=self.positions,
             auth=AuthService(self.otp_sender, cfg.auth),
             riders=RiderService(self.positions, events, cfg.fees),
             payments=payments, dispatch=dispatch, trips=trips,
````

Altere `server/app/services/quotes.py`:

````diff
--- a/server/app/services/quotes.py
+++ b/server/app/services/quotes.py
@@ -9,7 +9,7 @@ from app.db import queries
 from app.db import repositories as repo
 from app.db.config_store import AppConfig
 from app.db.models import QuoteRow, UserRow
-from app.domain.geo import GeoPoint
+from app.domain.geo import GeoPoint, haversine_m
 from app.domain.ids import new_id
 from app.domain.maps import MapsProvider
 from app.domain.pricing import final_price_cents, price_reason, smooth_factor, target_factor
@@ -37,6 +37,15 @@ class Quote:
     destination: GeoPoint
     pickup_text: str
     destination_text: str
+    eta_seconds: int | None = None      # estimativa de quando a moto livre mais perto chega; None se não há moto
+    nearby_riders: int = 0
+    route: tuple[tuple[float, float], ...] = ()
+
+
+# "Chega em X min" da tela de confirmação: linha reta até a moto livre mais perto, com a rua 30% mais longa,
+# a cerca de 25 km/h. É uma estimativa sem custo de mapa; o tempo de verdade vem da procura.
+_STREET_FACTOR = 1.3
+_ESTIMATED_SPEED_MPS = 7.0
 
 
 def passenger_block_reason(session: Session, passenger_id: str) -> str | None:
@@ -76,11 +85,20 @@ class QuoteService:
         reason_blocked = passenger_block_reason(session, passenger_id)
         if reason_blocked:
             raise NotAllowed(reason_blocked)
+        straight_m = haversine_m(pickup, destination)
+        if straight_m < self.cfg.rides.min_trip_m:
+            raise NotAllowed("A origem e o destino estão muito perto. Escolha outro destino.")
+        if straight_m > self.cfg.rides.max_trip_m:
+            raise NotAllowed("Esse destino é longe demais para uma corrida de moto.")
         route = self.maps.route(pickup, destination)
         near = self.positions.nearby(
             pickup, self.cfg.dispatch.search_radius_m, now, self.cfg.dispatch.position_max_age_s
         )
-        free = len(queries.free_online_rider_ids(session, [rider_id for rider_id, _ in near]))
+        free_ids = set(queries.free_online_rider_ids(session, [rider_id for rider_id, _ in near]))
+        free = len(free_ids)
+        nearest = next((point for rider_id, point in near if rider_id in free_ids), None)
+        eta_seconds = None if nearest is None else int(haversine_m(pickup, nearest) * _STREET_FACTOR / _ESTIMATED_SPEED_MPS)
+        route_points = tuple((point.lat, point.lng) for point in route.points)
         pending = queries.count_searching_rides(session)
         state = self.factors.get()
         if state is None or now - state[1] >= self.cfg.pricing.factor_interval_s:
@@ -94,6 +112,7 @@ class QuoteService:
             quote_id=new_id("q"), price_cents=price, distance_m=route.distance_m, duration_s=route.duration_s,
             factor=factor, reason=price_reason(factor), expires_at=now + self.cfg.rides.quote_ttl_s,
             pickup=pickup, destination=destination, pickup_text=pickup_text, destination_text=destination_text,
+            eta_seconds=eta_seconds, nearby_riders=free, route=route_points,
         )
         session.add(
             QuoteRow(
@@ -101,7 +120,8 @@ class QuoteService:
                 pickup_lat=pickup.lat, pickup_lng=pickup.lng, dest_lat=destination.lat, dest_lng=destination.lng,
                 pickup_text=pickup_text[:200], dest_text=destination_text[:200],
                 distance_m=route.distance_m, duration_s=route.duration_s, price_cents=price,
-                factor=factor, reason=quote.reason, created_at=now, expires_at=quote.expires_at,
+                factor=factor, reason=quote.reason, route=[list(p) for p in route_points],
+                created_at=now, expires_at=quote.expires_at,
             )
         )
         session.flush()
````

Altere `server/app/services/ride_requests.py`:

````diff
--- a/server/app/services/ride_requests.py
+++ b/server/app/services/ride_requests.py
@@ -5,6 +5,7 @@ import secrets
 from typing import Protocol
 
 from sqlalchemy import select
+from sqlalchemy.exc import IntegrityError
 from sqlalchemy.orm import Session
 
 from app.db import repositories as repo
@@ -47,7 +48,11 @@ class RideRequestService:
             payment_method=method, pin=f"{secrets.randbelow(10000):04d}",
         )
         start_search(ride, now)
-        repo.add_ride(session, ride)
+        try:
+            with session.begin_nested():
+                repo.add_ride(session, ride)
+        except IntegrityError:      # o índice do banco (uma corrida aberta por passageiro) é a última barreira
+            raise NotAllowed("Você já tem uma corrida em andamento.") from None
         repo.set_ride_details(
             session, ride.ride_id,
             repo.RideDetails(
@@ -55,6 +60,7 @@ class RideRequestService:
                 destination=GeoPoint(quote.dest_lat, quote.dest_lng),
                 pickup_text=quote.pickup_text, destination_text=quote.dest_text,
                 distance_m=quote.distance_m, price_factor=quote.factor, price_reason=quote.reason,
+                route=tuple((float(lat), float(lng)) for lat, lng in (quote.route or ())),
             ),
         )
         quote.used = True
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_passenger_routes.py tests/services/test_quotes_api.py tests/services/test_ride_requests_api.py`
Expected: `38 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `558 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): rotas do passageiro (preço, pedido, cancelamento, estado, contato de emergência)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 8: Motoqueiro: disponibilidade, posição, ofertas e andamento da corrida

O motoqueiro pelo celular: estado (cadastro, conta, oferta pendente, corrida, fila, pagamento esperado), ficar disponível, posição a cada ~4 s (que também acompanha o passageiro), a entrada de R$ 50, aceitar e recusar oferta e as etapas da corrida. O código de 4 dígitos ganha trava contra adivinhação. Três ajustes dos serviços do 2B: a oferta guarda o tempo de chegada, aceitar reconfere se o motoqueiro ainda está disponível e a 10ª corrida tira o motoqueiro de disponível.

**Files:**
- Modify: `server/app/api/errors.py`
- Modify: `server/app/api/routes/rider.py`
- Modify: `server/app/api/views.py`
- Modify: `server/app/db/queries.py`
- Modify: `server/app/infra/redis_store.py`
- Modify: `server/app/services/dispatch.py`
- Modify: `server/app/services/trips.py`
- Test: `server/tests/api/test_rider_routes.py` (novo)
- Test: `server/tests/infra/test_stores_api.py` (alterado)
- Test: `server/tests/services/test_dispatch.py` (alterado)
- Test: `server/tests/services/test_trips.py` (alterado)

**Interfaces:**
- Consumes: `DispatchService`, `TripService`, `RiderService`, `PaymentService.start_entry_charge`, `limiter`, as visões da Tarefa 7.
- Produces: `offer_payload(ride, details, *, eta_seconds, will_queue, expires_at) -> dict` (em `app.services.dispatch`; serve ao aviso e ao estado); `RateLimiter.count(key, window_s, now) -> int`; `queries.pending_offer_for_rider`, `rider_unpaid_cash_ride_id`, `rider_context(session, rider_id) -> RiderContext | None`; `views.rider_ride_view(unit, ride_id)` e `rider_state(unit, rider_id)`; regra de erro `WrongPin → 422 wrong_pin`; rotas `/v1/rider/state`, `/online`, `/offline`, `/position`, `/entry-charge`, `/offers/{id}/accept|decline`, `/rides/{id}/arrive|helmet|start|complete|cash-received`; o aviso `entry_required`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/api/test_rider_routes.py`:

````python
import datetime as dt

import pytest

from app.db import repositories as repo
from app.db.models import RiderProfileRow, UserRow
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def pedir(client, pax, metodo="pix"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    resposta = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def aceitar(client, rider, ride_id):
    resposta = client.post(f"/v1/rider/offers/{ride_id}/accept", headers=rider.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def pagar_pix(runtime, session, ride_id):
    cobranca = repo.get_current_charge_id(session, ride_id)
    runtime.run(lambda u: u.payments.on_provider_event(u.session, runtime.provider.mark_paid(cobranca)))


def acao(client, rider, ride_id, nome, **corpo):
    return client.post(f"/v1/rider/rides/{ride_id}/{nome}", json=corpo or None, headers=rider.headers)


# --- estado e disponibilidade -----------------------------------------------------------------


def test_estado_de_quem_ainda_nao_se_cadastrou(client, runtime):
    novo = login(client, runtime, "75 99999-0002", "rider")
    estado = client.get("/v1/rider/state", headers=novo.headers).json()
    assert estado["registration"] == {"status": "not_registered"}
    assert estado["account"] is None and estado["offer"] is None and estado["ride"] is None


def test_estado_do_motoqueiro_aprovado_mostra_conta_e_nota(client, rider):
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "approved" and estado["registration"]["online"] is True
    assert estado["registration"]["rating"] is None
    assert estado["account"] == {
        "completed_rides": 0, "trial_rides": 10, "entry_paid": False, "entry_fee_cents": 5000,
        "needs_entry": False, "cash_debt_cents": 0, "cash_debt_limit_cents": 1000,
    }
    assert (estado["offer"], estado["ride"], estado["queued_ride"], estado["awaiting_payment"]) == (None,) * 4


def test_ficar_disponivel_e_parar(client, rider, session):
    assert client.post("/v1/rider/offline", headers=rider.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).online is False
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    assert session.get(RiderProfileRow, rider.user_id).online is True


@pytest.mark.parametrize(
    "preparar, codigo",
    [
        (lambda p, u: setattr(p, "status", "pending"), "not_approved"),
        (lambda p, u: setattr(p, "status", "blocked"), "blocked"),
        (lambda p, u: setattr(p, "cnh_expires_on", dt.date(2020, 1, 1)), "documents_expired"),
        (lambda p, u: setattr(p, "completed_rides", 10), "entry_pending"),
    ],
)
def test_nao_pode_ficar_disponivel_e_o_codigo_diz_por_que(client, rider, session, preparar, codigo):
    perfil = session.get(RiderProfileRow, rider.user_id)
    preparar(perfil, session.get(UserRow, rider.user_id))
    session.flush()
    resposta = client.post("/v1/rider/online", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == codigo


def test_cobranca_da_entrada_uma_so_e_para_quem_ainda_nao_pagou(client, rider, runtime, session):
    resposta = client.post("/v1/rider/entry-charge", headers=rider.headers)
    assert resposta.status_code == 201
    cobranca = resposta.json()
    assert cobranca["amount_cents"] == 5000 and cobranca["br_code"].startswith("fake-pix|")
    assert client.post("/v1/rider/entry-charge", headers=rider.headers).json()["charge_id"] == cobranca["charge_id"]
    runtime.run(lambda u: u.payments.on_provider_event(u.session, runtime.provider.mark_paid(cobranca["charge_id"])))
    resposta = client.post("/v1/rider/entry-charge", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"


# --- posição ----------------------------------------------------------------------------------


def test_posicao_do_motoqueiro_disponivel_vai_para_a_loja(client, rider, runtime):
    ponto = pt(500, 100)
    resposta = client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers)
    assert resposta.status_code == 204
    assert runtime.positions.get(rider.user_id).lat == pytest.approx(ponto.lat)


def test_posicao_de_quem_esta_parado_e_ignorada(client, rider, runtime):
    client.post("/v1/rider/offline", headers=rider.headers)
    runtime.positions.remove(rider.user_id)
    resposta = client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert resposta.status_code == 204 and runtime.positions.get(rider.user_id) is None


@pytest.mark.parametrize("corpo", [{"lat": 95, "lng": 0}, {"lat": 0, "lng": 200}, {"lat": "a", "lng": 0}, {}])
def test_posicao_invalida_e_422(client, rider, corpo):
    assert client.post("/v1/rider/position", json=corpo, headers=rider.headers).status_code == 422


def test_durante_a_corrida_a_posicao_chega_ao_passageiro(client, pax, rider, runtime, session, listen):
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    avisos = listen(pax.user_id)
    client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert avisos.types == ["rider_position"]
    assert avisos.messages[0]["data"] == {"ride_id": corrida["ride_id"], "lat": ORIGIN.lat, "lng": ORIGIN.lng}


def test_sem_corrida_a_posicao_nao_vai_para_ninguem(client, pax, rider, listen):
    avisos = listen(pax.user_id)
    client.post("/v1/rider/position", json={"lat": ORIGIN.lat, "lng": ORIGIN.lng}, headers=rider.headers)
    assert avisos.messages == []


# --- ofertas ----------------------------------------------------------------------------------


def test_oferta_aparece_no_estado_igual_ao_aviso(client, pax, rider, listen):
    avisos = listen(rider.user_id)
    corrida = pedir(client, pax)
    oferta = client.get("/v1/rider/state", headers=rider.headers).json()["offer"]
    assert oferta == avisos.messages[0]["data"]
    assert oferta["ride_id"] == corrida["ride_id"] and oferta["payment_method"] == "pix"
    assert oferta["will_queue"] is False and oferta["seconds_to_pickup"] > 0


def test_aceitar_mostra_a_corrida_do_lado_do_motoqueiro_e_avisa_o_passageiro(client, pax, rider, listen):
    avisos = listen(pax.user_id)
    corrida = pedir(client, pax)
    ride = aceitar(client, rider, corrida["ride_id"])
    assert ride["state"] == "accepted" and ride["passenger"] == {"name": "Ana"} and ride["fee_cents"] == 100
    assert "pin" not in ride and ride["pix_paid"] is False and ride["method"] == "pix"
    assert ride["pickup"]["text"] == "Rua A" and ride["destination"]["text"] == "Feira livre"
    aviso = next(m for m in avisos.messages if m["type"] == "rider_accepted")["data"]
    assert aviso["pin"] == corrida["pin"] and aviso["pay"]["amount_cents"] == corrida["price_cents"]
    assert client.get("/v1/rider/state", headers=rider.headers).json()["ride"]["ride_id"] == corrida["ride_id"]


def test_recusar_passa_a_oferta_adiante_sem_penalidade(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/decline", headers=rider.headers).status_code == 204
    assert client.get("/v1/rider/state", headers=rider.headers).json()["offer"] is None
    assert client.get("/v1/rider/state", headers=outro.headers).json()["offer"]["ride_id"] == corrida["ride_id"]


def test_oferta_que_nao_e_sua_ou_que_venceu(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=outro.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "offer_gone"
    clock.advance(16)
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "offer_gone"
    assert client.post("/v1/rider/offers/nao-existe/decline", headers=rider.headers).status_code == 404
    assert client.post("/v1/rider/offers/nao-existe/accept", headers=rider.headers).status_code == 404


# --- andamento ------------------------------------------------------------------------------------


def test_corrida_pix_do_aceite_ao_fim_com_avisos_ao_passageiro(client, pax, rider, runtime, session, listen):
    avisos = listen(pax.user_id)
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    rid = corrida["ride_id"]

    assert acao(client, rider, rid, "arrive").status_code == 200
    assert acao(client, rider, rid, "helmet").status_code == 200
    resposta = acao(client, rider, rid, "start", pin=corrida["pin"])
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"      # Pix não pago
    pagar_pix(runtime, session, rid)
    errado = "0000" if corrida["pin"] != "0000" else "1111"
    resposta = acao(client, rider, rid, "start", pin=errado)
    assert resposta.status_code == 422 and resposta.json()["error"]["code"] == "wrong_pin"
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).json()["state"] == "in_progress"
    final = acao(client, rider, rid, "complete").json()
    assert final["state"] == "completed" and final["end_payment"] is None
    assert {"rider_accepted", "rider_arrived", "trip_started", "trip_completed"} <= set(avisos.types)

    assert client.post(f"/v1/rides/{rid}/rating", json={"stars": 5}, headers=rider.headers).status_code == 204
    assert client.get("/v1/rider/state", headers=rider.headers).json()["account"]["completed_rides"] == 1


def test_corrida_em_dinheiro_termina_com_qr_e_motoqueiro_confirma(client, pax, rider, runtime, session):
    corrida = pedir(client, pax, "cash")
    rid = corrida["ride_id"]
    aceitar(client, rider, rid)
    acao(client, rider, rid, "arrive")
    acao(client, rider, rid, "helmet")
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).status_code == 200
    final = acao(client, rider, rid, "complete").json()
    assert final["end_payment"]["amount_cents"] == corrida["price_cents"] and final["end_payment"]["blocked"] is False
    assert final["end_payment"]["charge_id"] == repo.get_current_charge_id(session, rid)
    espera = client.get("/v1/rider/state", headers=rider.headers).json()["awaiting_payment"]
    assert espera["ride_id"] == rid

    assert acao(client, rider, rid, "cash-received").status_code == 204
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["awaiting_payment"] is None and estado["account"]["cash_debt_cents"] == 100


def test_codigo_errado_demais_trava_a_corrida_por_dez_minutos(client, pax, rider, clock, runtime, session):
    corrida = pedir(client, pax)
    rid = corrida["ride_id"]
    aceitar(client, rider, rid)
    acao(client, rider, rid, "arrive")
    acao(client, rider, rid, "helmet")
    pagar_pix(runtime, session, rid)
    errado = "0000" if corrida["pin"] != "0000" else "1111"
    for _ in range(5):
        assert acao(client, rider, rid, "start", pin=errado).status_code == 422
    resposta = acao(client, rider, rid, "start", pin=corrida["pin"])
    assert resposta.status_code == 429 and resposta.json()["error"]["code"] == "too_many_requests"
    clock.advance(601)
    assert acao(client, rider, rid, "start", pin=corrida["pin"]).status_code == 200


@pytest.mark.parametrize("pin", ["12", "12345", "abcd", ""])
def test_codigo_com_formato_ruim_e_422(client, pax, rider, pin):
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    assert acao(client, rider, corrida["ride_id"], "start", pin=pin).status_code == 422


def test_so_o_motoqueiro_da_corrida_mexe_nela(client, pax, rider, runtime, session, clock):
    online_rider(session, runtime, clock, 2, pt(900, 0))
    outro = login(client, runtime, rider_phone(2), "rider")
    corrida = pedir(client, pax)
    aceitar(client, rider, corrida["ride_id"])
    for nome in ("arrive", "helmet", "complete", "cash-received"):
        resposta = acao(client, outro, corrida["ride_id"], nome)
        assert resposta.status_code == 403 and resposta.json()["error"]["code"] == "not_your_ride", nome
    assert acao(client, rider, "nao-existe", "arrive").status_code == 404


def test_rotas_do_motoqueiro_sao_so_do_motoqueiro(client, pax):
    for metodo, url in (
        ("get", "/v1/rider/state"), ("post", "/v1/rider/online"), ("post", "/v1/rider/offline"),
        ("post", "/v1/rider/position"), ("post", "/v1/rider/entry-charge"), ("post", "/v1/rider/offers/x/accept"),
        ("post", "/v1/rider/rides/x/arrive"),
    ):
        assert getattr(client, metodo)(url, headers=pax.headers).status_code == 403, url
        assert getattr(client, metodo)(url).status_code == 401, url
````

Altere `server/tests/infra/test_stores_api.py`:

````diff
--- a/server/tests/infra/test_stores_api.py
+++ b/server/tests/infra/test_stores_api.py
@@ -41,6 +41,15 @@ def test_limitador_deixa_passar_ate_o_limite_e_zera_na_janela_seguinte(limiter):
     assert limiter.hit("pin:ride-1", 3, 600, now=1600.0) is True        # janela seguinte
 
 
+def test_limitador_conta_sem_gastar_tentativa(limiter):
+    assert limiter.count("pin:ride-1", 600, now=1000.0) == 0
+    limiter.hit("pin:ride-1", 3, 600, now=1000.0)
+    limiter.hit("pin:ride-1", 3, 600, now=1001.0)
+    assert limiter.count("pin:ride-1", 600, now=1002.0) == 2
+    assert limiter.count("pin:ride-1", 600, now=1002.0) == 2
+    assert limiter.count("pin:ride-1", 600, now=1600.0) == 0          # janela seguinte
+
+
 def test_pix_fora_do_ar_volta_sozinho_depois_do_prazo(health):
     assert health.is_down(100.0) is False
     health.mark_down(100.0, for_s=60.0)
````

Altere `server/tests/services/test_dispatch.py`:

````diff
--- a/server/tests/services/test_dispatch.py
+++ b/server/tests/services/test_dispatch.py
@@ -345,3 +345,28 @@ def test_ainda_calcula_a_rota_da_moto_que_esta_terminando_perto(dispatch_contand
     mapa.chamadas = 0
     assert dispatch_contando.offer_next(session, "ride-1", AGORA) == rider
     assert mapa.chamadas >= 1
+
+
+def test_oferta_guarda_o_tempo_ate_o_passageiro_para_o_app_mostrar_ao_reconectar(dispatch, session, positions, events):
+    mundo(session, positions)
+    dispatch.offer_next(session, "ride-1", AGORA)
+    aviso = next(e for e in events.events if e.type == "offer")
+    assert session.query(RideOfferRow).one().eta_seconds == aviso.payload["seconds_to_pickup"] > 0
+
+
+def test_motoqueiro_que_ficou_indisponivel_depois_da_oferta_nao_consegue_aceitar(dispatch, session, positions):
+    # Roteiro do 2B (menores): `accept_offer` não reconferia o bloqueio.
+    from app.db.models import RiderProfileRow, UserRow
+
+    mundo(session, positions)
+    dispatch.offer_next(session, "ride-1", AGORA)
+    session.get(RiderProfileRow, "r1").online = False
+    session.flush()
+    with pytest.raises(OfferGone, match="disponível"):
+        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
+    session.get(RiderProfileRow, "r1").online = True
+    session.get(UserRow, "r1").is_blocked = True
+    session.flush()
+    with pytest.raises(OfferGone, match="disponível"):
+        dispatch.accept_offer(session, "r1", "ride-1", AGORA + 3)
+    assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
````

Altere `server/tests/services/test_trips.py`:

````diff
--- a/server/tests/services/test_trips.py
+++ b/server/tests/services/test_trips.py
@@ -290,3 +290,27 @@ def test_corrida_em_dinheiro_termina_mesmo_com_o_provedor_de_pix_fora_do_ar(sess
     w.trips.confirm_cash_received(session, "r1", "ride-1", AGORA + 600)       # o dinheiro continua valendo
     assert repo.get_rider_account(session, "r1").cash_debt_cents == 100
 
+
+
+def _faz_corrida_numero(w, session, positions, completadas_antes):
+    add_passenger(session)
+    aceitar(session, positions, w)
+    pagar(session, w)
+    acc = repo.get_rider_account(session, "r1", for_update=True)
+    acc.completed_rides = completadas_antes
+    repo.save_rider_account(session, acc)
+    ate_o_fim(session, w)
+
+
+def test_decima_corrida_tira_o_motoqueiro_de_disponivel_e_avisa_da_entrada(w, session, positions, events):
+    # Roteiro do 2B (menores): na 10ª corrida sem entrada ele continuava "disponível".
+    _faz_corrida_numero(w, session, positions, completadas_antes=9)
+    assert session.get(RiderProfileRow, "r1").online is False
+    aviso = next(e for e in events.events if e.type == "entry_required")
+    assert aviso.user_id == "r1" and aviso.payload == {"entry_fee_cents": 5000}
+
+
+def test_nona_corrida_nao_mexe_na_disponibilidade(w, session, positions, events):
+    _faz_corrida_numero(w, session, positions, completadas_antes=8)
+    assert session.get(RiderProfileRow, "r1").online is True
+    assert "entry_required" not in tipos(events, "r1")
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q \
  tests/api/test_rider_routes.py \
  tests/infra/test_stores_api.py \
  tests/services/test_dispatch.py \
  tests/services/test_trips.py`
Expected: FAIL — `33 failed, 48 passed` (primeiro erro: `KeyError: 'registration'`).

- [ ] **Step 3: Implementar**

Altere `server/app/api/errors.py`:

````diff
--- a/server/app/api/errors.py
+++ b/server/app/api/errors.py
@@ -15,7 +15,7 @@ from starlette.exceptions import HTTPException as StarletteHTTPException
 
 from app.domain.payments import PaymentProviderError
 from app.infra.documents import UploadError
-from app.domain.rides import InvalidTransition
+from app.domain.rides import InvalidTransition, WrongPin
 from app.services.auth import TooManyRequests
 from app.services.dispatch import OfferGone
 from app.services.quotes import NotAllowed, QuoteExpired
@@ -51,6 +51,7 @@ _RULES: dict[type[Exception], _Rule] = {
     AlreadyRated: _Rule(409, "already_rated"),
     InvalidTransition: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual da corrida."),
     InvalidState: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual do cadastro."),
+    WrongPin: _Rule(422, "wrong_pin", "Código errado. Confira os 4 dígitos com o passageiro."),
     RegistrationError: _Rule(422, "invalid"),
     ValueError: _Rule(422, "invalid"),
     PaymentProviderError: _Rule(503, "payment_unavailable", "O Pix está instável agora. Tente de novo em instantes."),
````

Altere `server/app/api/routes/rider.py`:

````diff
--- a/server/app/api/routes/rider.py
+++ b/server/app/api/routes/rider.py
@@ -1,4 +1,4 @@
-"""Rotas do motoqueiro: documentos e cadastro. (Disponibilidade e corridas entram na próxima tarefa.)"""
+"""Rotas do motoqueiro: cadastro, disponibilidade, posição, ofertas e andamento da corrida."""
 from __future__ import annotations
 
 import datetime as dt
@@ -9,7 +9,11 @@ from fastapi.concurrency import run_in_threadpool
 from pydantic import BaseModel, Field
 
 from app.api.deps import get_runtime, rider_user
+from app.api.views import rider_ride_view, rider_state
+from app.db import queries
 from app.domain.clock import local_date
+from app.domain.geo import GeoPoint
+from app.domain.rides import WrongPin
 from app.infra.documents import KINDS, MAX_UPLOAD_BYTES, DocumentStore, UploadError
 from app.services.auth import AuthUser, TooManyRequests
 from app.services.riders import RegistrationError
@@ -18,6 +22,9 @@ router = APIRouter(prefix="/v1/rider", tags=["motoqueiro"])
 
 DocKind = Literal["selfie", "cnh", "crlv"]
 UPLOADS_PER_HOUR = 30
+PIN_ATTEMPTS = 5            # códigos errados por corrida...
+PIN_WINDOW_S = 600          # ...nesta janela, depois trava (4 dígitos não podem ser adivinhados no tapa)
+_ON_THE_MOVE = ("accepted", "arrived", "in_progress")
 _KIND_NAMES = {"selfie": "o seu rosto (selfie)", "cnh": "a CNH", "crlv": "o documento da moto"}
 
 
@@ -34,6 +41,15 @@ class RegisterIn(BaseModel):
     crlv_expires_on: dt.date
 
 
+class PositionIn(BaseModel):
+    lat: float = Field(ge=-90, le=90)
+    lng: float = Field(ge=-180, le=180)
+
+
+class StartIn(BaseModel):
+    pin: str = Field(pattern=r"^\d{4}$")
+
+
 class RenewIn(BaseModel):
     cnh_expires_on: dt.date
     crlv_expires_on: dt.date
@@ -105,4 +121,111 @@ def renew_documents(body: RenewIn, request: Request, user: AuthUser = Depends(ri
     return Response(status_code=204)
 
 
+@router.get("/state")
+def state(request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    return get_runtime(request).run(lambda unit: rider_state(unit, user.user_id))
+
+
+@router.post("/online", status_code=204)
+def go_online(request: Request, user: AuthUser = Depends(rider_user)) -> Response:
+    get_runtime(request).run(lambda unit: unit.riders.go_online(unit.session, user.user_id, local_date(unit.now)))
+    return Response(status_code=204)
+
+
+@router.post("/offline", status_code=204)
+def go_offline(request: Request, user: AuthUser = Depends(rider_user)) -> Response:
+    get_runtime(request).run(lambda unit: unit.riders.go_offline(unit.session, user.user_id))
+    return Response(status_code=204)
+
+
+@router.post("/position", status_code=204)
+def report_position(body: PositionIn, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
+    """A cada ~4 s enquanto disponível. Quem está parado não entra no mapa; na corrida, o passageiro acompanha."""
+
+    def work(unit):
+        context = queries.rider_context(unit.session, user.user_id)
+        if context is None or not context.online:
+            return
+        unit.riders.report_position(user.user_id, GeoPoint(body.lat, body.lng), unit.now)
+        if context.ride_id is not None and context.ride_state in _ON_THE_MOVE:
+            unit.events.add(
+                context.passenger_id, "rider_position", {"ride_id": context.ride_id, "lat": body.lat, "lng": body.lng}
+            )
+
+    get_runtime(request).run(work)
+    return Response(status_code=204)
+
+
+@router.post("/entry-charge", status_code=201)
+def entry_charge(request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    def work(unit):
+        charge = unit.payments.start_entry_charge(unit.session, user.user_id)
+        return {"charge_id": charge.charge_id, "amount_cents": charge.amount_cents, "br_code": charge.br_code}
+
+    return get_runtime(request).run(work)
+
+
+@router.post("/offers/{ride_id}/accept")
+def accept_offer(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    def work(unit):
+        unit.dispatch.accept_offer(unit.session, user.user_id, ride_id, unit.now)
+        return rider_ride_view(unit, ride_id)
+
+    return get_runtime(request).run(work)
+
+
+@router.post("/offers/{ride_id}/decline", status_code=204)
+def decline_offer(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
+    get_runtime(request).run(lambda unit: unit.dispatch.decline_offer(unit.session, user.user_id, ride_id, unit.now))
+    return Response(status_code=204)
+
+
+def _step(request: Request, user: AuthUser, ride_id: str, action) -> dict:
+    def work(unit):
+        action(unit)
+        return rider_ride_view(unit, ride_id)
+
+    return get_runtime(request).run(work)
+
+
+@router.post("/rides/{ride_id}/arrive")
+def arrive(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    return _step(request, user, ride_id, lambda u: u.trips.arrive(u.session, user.user_id, ride_id, u.now))
+
+
+@router.post("/rides/{ride_id}/helmet")
+def confirm_helmet(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    return _step(request, user, ride_id, lambda u: u.trips.confirm_helmet(u.session, user.user_id, ride_id, u.now))
+
+
+@router.post("/rides/{ride_id}/start")
+def start_trip(ride_id: str, body: StartIn, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    runtime = get_runtime(request)
+    key = f"pin:{ride_id}"
+
+    def action(unit):
+        if runtime.limiter.count(key, PIN_WINDOW_S, unit.now) >= PIN_ATTEMPTS:
+            raise TooManyRequests("Muitas tentativas de código. Espere alguns minutos e confira com o passageiro.")
+        try:
+            unit.trips.start_trip(unit.session, user.user_id, ride_id, body.pin, unit.now)
+        except WrongPin:
+            runtime.limiter.hit(key, PIN_ATTEMPTS, PIN_WINDOW_S, unit.now)
+            raise
+
+    return _step(request, user, ride_id, action)
+
+
+@router.post("/rides/{ride_id}/complete")
+def complete_trip(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
+    return _step(request, user, ride_id, lambda u: u.trips.complete_trip(u.session, user.user_id, ride_id, u.now))
+
+
+@router.post("/rides/{ride_id}/cash-received", status_code=204)
+def cash_received(ride_id: str, request: Request, user: AuthUser = Depends(rider_user)) -> Response:
+    get_runtime(request).run(
+        lambda unit: unit.trips.confirm_cash_received(unit.session, user.user_id, ride_id, unit.now)
+    )
+    return Response(status_code=204)
+
+
 assert set(DocKind.__args__) == set(KINDS)      # a lista da rota e a do armazenamento não podem divergir
````

Altere `server/app/api/views.py`:

````diff
--- a/server/app/api/views.py
+++ b/server/app/api/views.py
@@ -3,9 +3,12 @@ from __future__ import annotations
 
 from app.db import queries
 from app.db import repositories as repo
+from app.db.models import RiderProfileRow, UserRow
+from app.domain.fees import offer_block_reason
 from app.domain.rides import Ride, RideState
 from app.domain.types import PaymentMethod
 from app.runtime import Unit
+from app.services.dispatch import offer_payload
 from app.services.quotes import Quote, passenger_block_reason
 
 _WITH_RIDER_ON_THE_MOVE = (RideState.ACCEPTED, RideState.ARRIVED, RideState.IN_PROGRESS)
@@ -99,3 +102,64 @@ def passenger_state(unit: Unit, passenger_id: str, payment_methods: list[str]) -
         "emergency_contact": None if contact is None else {"name": contact.name, "phone": contact.phone},
         "payment_methods": payment_methods,
     }
+
+
+# --- motoqueiro ----------------------------------------------------------------------------------------
+
+
+def rider_ride_view(unit: Unit, ride_id: str) -> dict:
+    ride = repo.get_ride(unit.session, ride_id)
+    details = repo.get_ride_details(unit.session, ride_id)
+    passenger = unit.session.get(UserRow, ride.passenger_id)
+    first_name = (passenger.name.split() or [""])[0] if passenger is not None else ""
+    return {
+        "ride_id": ride.ride_id, "state": ride.state.value, "queued": ride.state is RideState.QUEUED,
+        "price_cents": ride.price_cents, "fee_cents": ride.fee_cents, "method": ride.payment_method.value,
+        "pix_paid": ride.pix_paid, "helmet_confirmed": ride.helmet_confirmed,
+        "passenger": {"name": first_name},      # o motoqueiro só vê o primeiro nome (o código fica com o passageiro)
+        "pickup": place(details.pickup.lat, details.pickup.lng, details.pickup_text),
+        "destination": place(details.destination.lat, details.destination.lng, details.destination_text),
+        "distance_m": details.distance_m, "end_payment": _end_payment(unit, ride),
+    }
+
+
+def rider_state(unit: Unit, rider_id: str) -> dict:
+    session = unit.session
+    profile = session.get(RiderProfileRow, rider_id)
+    if profile is None:
+        return {
+            "registration": {"status": "not_registered"}, "account": None, "offer": None, "ride": None,
+            "queued_ride": None, "awaiting_payment": None,
+        }
+    fees = unit.cfg.fees
+    account = repo.get_rider_account(session, rider_id)
+    rating = round(profile.rating_sum / profile.rating_count, 1) if profile.rating_count else None
+    offer_row = queries.pending_offer_for_rider(session, rider_id)
+    offer = None
+    if offer_row is not None:
+        ride = repo.get_ride(session, offer_row.ride_id)
+        offer = offer_payload(
+            ride, repo.get_ride_details(session, offer_row.ride_id), eta_seconds=offer_row.eta_seconds,
+            will_queue=offer_row.will_queue, expires_at=offer_row.expires_at,
+        )
+    active_id = queries.rider_active_ride_id(session, rider_id)
+    queued_id = queries.queued_ride_id_of_rider(session, rider_id)
+    unpaid_id = queries.rider_unpaid_cash_ride_id(session, rider_id)
+    return {
+        "registration": {
+            "status": profile.status, "online": profile.online, "reason": profile.rejected_reason,
+            "rating": rating, "rating_count": profile.rating_count,
+            "cnh_expires_on": profile.cnh_expires_on.isoformat() if profile.cnh_expires_on else None,
+            "crlv_expires_on": profile.crlv_expires_on.isoformat() if profile.crlv_expires_on else None,
+        },
+        "account": {
+            "completed_rides": account.completed_rides, "trial_rides": fees.trial_rides,
+            "entry_paid": account.entry_paid, "entry_fee_cents": fees.entry_fee_cents,
+            "needs_entry": offer_block_reason(account, fees) is not None,
+            "cash_debt_cents": account.cash_debt_cents, "cash_debt_limit_cents": fees.cash_debt_limit_cents,
+        },
+        "offer": offer,
+        "ride": rider_ride_view(unit, active_id) if active_id else None,
+        "queued_ride": rider_ride_view(unit, queued_id) if queued_id else None,
+        "awaiting_payment": rider_ride_view(unit, unpaid_id) if unpaid_id else None,
+    }
````

Altere `server/app/db/queries.py`:

````diff
--- a/server/app/db/queries.py
+++ b/server/app/db/queries.py
@@ -316,3 +316,47 @@ def passenger_rode_with(session: Session, passenger_id: str, rider_id: str) -> b
         )
         .limit(1)
     ).first() is not None
+
+
+def pending_offer_for_rider(session: Session, rider_id: str) -> RideOfferRow | None:
+    return session.execute(
+        select(RideOfferRow).where(RideOfferRow.rider_id == rider_id, RideOfferRow.status == "pending")
+    ).scalar_one_or_none()
+
+
+def rider_unpaid_cash_ride_id(session: Session, rider_id: str) -> str | None:
+    """A corrida em dinheiro mais recente que o motoqueiro terminou e ainda está sem pagamento confirmado."""
+    return session.execute(
+        select(RideRow.id)
+        .where(
+            RideRow.rider_id == rider_id,
+            RideRow.state == RideState.COMPLETED.value,
+            RideRow.payment_method == "cash",
+            RideRow.end_payment_confirmed.is_(False),
+        )
+        .order_by(RideRow.completed_at.desc())
+        .limit(1)
+    ).scalar_one_or_none()
+
+
+@dataclass(frozen=True)
+class RiderContext:
+    online: bool
+    ride_id: str | None
+    passenger_id: str | None
+    ride_state: str | None
+
+
+def rider_context(session: Session, rider_id: str) -> RiderContext | None:
+    """O que o servidor precisa saber a cada posição recebida: está disponível? tem corrida em andamento?"""
+    online = session.execute(
+        select(RiderProfileRow.online).where(RiderProfileRow.user_id == rider_id)
+    ).scalar_one_or_none()
+    if online is None:
+        return None
+    ride = session.execute(
+        select(RideRow.id, RideRow.passenger_id, RideRow.state)
+        .where(RideRow.rider_id == rider_id, RideRow.state.in_(_ACTIVE))
+        .limit(1)
+    ).first()
+    return RiderContext(bool(online), *(tuple(ride) if ride else (None, None, None)))
````

Altere `server/app/infra/redis_store.py`:

````diff
--- a/server/app/infra/redis_store.py
+++ b/server/app/infra/redis_store.py
@@ -212,6 +212,9 @@ class RateLimiter(Protocol):
     def hit(self, key: str, limit: int, window_s: float, now: float) -> bool:
         """Conta mais uma tentativa em `key`. Devolve False quando passou de `limit` na janela atual."""
 
+    def count(self, key: str, window_s: float, now: float) -> int:
+        """Quantas tentativas já foram contadas na janela atual (sem contar mais uma)."""
+
 
 class InMemoryRateLimiter:
     def __init__(self) -> None:
@@ -222,6 +225,9 @@ class InMemoryRateLimiter:
         self._counts[bucket] = self._counts.get(bucket, 0) + 1
         return self._counts[bucket] <= limit
 
+    def count(self, key: str, window_s: float, now: float) -> int:
+        return self._counts.get((key, int(now // window_s)), 0)
+
 
 class RedisRateLimiter:
     """Janela fixa por chave. O instante vem de quem chama (`now`), como no resto do servidor."""
@@ -238,6 +244,9 @@ class RedisRateLimiter:
         count, _ = pipe.execute()
         return int(count) <= limit
 
+    def count(self, key: str, window_s: float, now: float) -> int:
+        return int(self.r.get(f"{self.prefix}{key}:{int(now // window_s)}") or 0)
+
 
 class PixHealth(Protocol):
     def mark_down(self, now: float, for_s: float) -> None: ...
````

Altere `server/app/services/dispatch.py`:

````diff
--- a/server/app/services/dispatch.py
+++ b/server/app/services/dispatch.py
@@ -32,6 +32,19 @@ class OfferGone(Exception):
     """A oferta não existe mais para este motoqueiro (venceu, foi para outro, ou a corrida mudou)."""
 
 
+def offer_payload(
+    ride: Ride, details: repo.RideDetails, *, eta_seconds: int | None, will_queue: bool, expires_at: float
+) -> dict:
+    """O que o motoqueiro vê numa oferta. Serve ao aviso em tempo real e ao estado que o app pede ao reconectar."""
+    return {
+        "ride_id": ride.ride_id, "price_cents": ride.price_cents, "payment_method": ride.payment_method.value,
+        "pickup": {"lat": details.pickup.lat, "lng": details.pickup.lng, "text": details.pickup_text},
+        "destination": {"lat": details.destination.lat, "lng": details.destination.lng, "text": details.destination_text},
+        "distance_m": details.distance_m, "seconds_to_pickup": eta_seconds,
+        "will_queue": will_queue, "expires_at": expires_at,
+    }
+
+
 class Reservations(Protocol):
     def reserve(self, rider_id: str, ride_id: str) -> bool: ...
 
@@ -109,7 +122,8 @@ class DispatchService:
                     session.add(
                         RideOfferRow(
                             ride_id=ride_id, rider_id=candidate.rider_id, status="pending",
-                            will_queue=candidate.will_queue, created_at=now, expires_at=now + dispatch_cfg.offer_timeout_s,
+                            will_queue=candidate.will_queue, eta_seconds=candidate.eta_seconds, created_at=now,
+                            expires_at=now + dispatch_cfg.offer_timeout_s,
                         )
                     )
                     session.flush()
@@ -119,15 +133,10 @@ class DispatchService:
             repo.log_ride_event(session, ride_id, "offered", {"rider_id": candidate.rider_id}, now)
             self.events.add(
                 candidate.rider_id, "offer",
-                {
-                    "ride_id": ride_id, "price_cents": ride.price_cents, "payment_method": ride.payment_method.value,
-                    "pickup": {"lat": details.pickup.lat, "lng": details.pickup.lng, "text": details.pickup_text},
-                    "destination": {
-                        "lat": details.destination.lat, "lng": details.destination.lng, "text": details.destination_text,
-                    },
-                    "distance_m": details.distance_m, "seconds_to_pickup": candidate.eta_seconds,
-                    "will_queue": candidate.will_queue, "expires_at": now + dispatch_cfg.offer_timeout_s,
-                },
+                offer_payload(
+                    ride, details, eta_seconds=candidate.eta_seconds, will_queue=candidate.will_queue,
+                    expires_at=now + dispatch_cfg.offer_timeout_s,
+                ),
             )
             return candidate.rider_id
         return None
@@ -144,6 +153,9 @@ class DispatchService:
             or offer.expires_at <= now
         ):
             raise OfferGone("Essa corrida já foi para outro motoqueiro.")
+        snapshot = queries.rider_snapshots(session, [rider_id]).get(rider_id)
+        if snapshot is None or not snapshot.available:      # parou, foi bloqueado ou perdeu a aprovação depois da oferta
+            raise OfferGone("Você não está disponível para essa corrida.")
         repo.get_rider_account(session, rider_id, for_update=True)
         busy = queries.rider_active_ride_id(session, rider_id) is not None
         number = queries.completed_rides_since(session, rider_id, local_day_start(now)) + (1 if busy else 0) + 1
````

Altere `server/app/services/trips.py`:

````diff
--- a/server/app/services/trips.py
+++ b/server/app/services/trips.py
@@ -87,6 +87,10 @@ class TripService:
         count_completed_ride(acc)
         repo.save_ride(session, ride)
         repo.save_rider_account(session, acc)
+        if offer_block_reason(acc, self.cfg.fees) is not None:
+            # chegou nas corridas de teste sem pagar a entrada: para de aparecer como disponível e o app avisa
+            session.get(RiderProfileRow, rider_id).online = False
+            self.events.add(rider_id, "entry_required", {"entry_fee_cents": self.cfg.fees.entry_fee_cents})
         repo.log_ride_event(session, ride_id, "completed", {}, now)
         pay = None
         if ride.payment_method is PaymentMethod.CASH:
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q \
  tests/api/test_rider_routes.py \
  tests/infra/test_stores_api.py \
  tests/services/test_dispatch.py \
  tests/services/test_trips.py`
Expected: `81 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `593 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): rotas do motoqueiro (estado, disponibilidade, posição, ofertas e corrida)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 9: Pagamentos: aviso assinado do provedor, cobrança, Pix fora do ar e rotas só de desenvolvimento

O aviso do provedor entra assinado (HMAC), é conferido com a cobrança guardada (valor e corrida) e tratado uma vez só. O app consulta a cobrança para desenhar o QR. O Pix pago e o Pix devolvido passam a avisar passageiro e motoqueiro. Quando o provedor falha, o servidor responde 503 e, por um minuto, só oferece dinheiro. Duas rotas só do modo de desenvolvimento deixam o simulador pegar o código de login e "pagar" um Pix.

**Files:**
- Modify: `server/app/api/app.py`
- Create: `server/app/api/body.py`
- Modify: `server/app/api/errors.py`
- Create: `server/app/api/routes/dev.py`
- Create: `server/app/api/routes/payments.py`
- Modify: `server/app/api/routes/rider.py`
- Create: `server/app/api/webhook.py`
- Modify: `server/app/runtime.py`
- Modify: `server/app/services/payments.py`
- Test: `server/tests/api/conftest.py` (alterado)
- Test: `server/tests/api/test_payments_routes.py` (novo)
- Test: `server/tests/api/test_runtime.py` (alterado)
- Test: `server/tests/services/test_payment_service.py` (alterado)

**Interfaces:**
- Consumes: `PaymentService.on_provider_event`, `repo.get_charge`, `Runtime.run`, `pix_health`.
- Produces: `app.api.body.read_limited(request, limit, too_big)`; `app.api.webhook`: `SIGNATURE_HEADER = "x-signature"`, `sign(secret, body) -> "sha256=<hex>"`, `WebhookVerifier`, `HmacVerifier(secret)`, `PixEvent`, `process_pix_event(runtime, event) -> "applied" | "refunded" | "duplicate" | "unknown_charge"`; `Runtime.webhook_verifier`; rotas `POST /v1/webhooks/pix`, `GET /v1/charges/{id}`, `GET /v1/dev/otp`, `POST /v1/dev/pix/{id}/pay`; avisos `pix_confirmed`, `payment_received` (Pix antes da corrida), `payment_refunded`; `PaymentProviderError` passa a marcar o Pix como fora do ar por 60 s.

- [ ] **Step 1: Escrever os testes que falham**

Altere `server/tests/api/conftest.py`:

````diff
--- a/server/tests/api/conftest.py
+++ b/server/tests/api/conftest.py
@@ -6,6 +6,7 @@ from app.adapters.fake_maps import FakeMaps
 from app.adapters.fake_otp import FakeOtpSender
 from app.adapters.fake_payments import FakePaymentProvider
 from app.api.app import create_app
+from app.api.webhook import HmacVerifier
 from app.domain.dispatch import ReservationBook
 from app.infra.documents import LocalDocumentStore
 from app.infra.redis_store import (
@@ -19,6 +20,7 @@ from app.realtime.hub import Hub
 from app.runtime import Runtime
 
 AGORA = 1_800_000_000.0
+WEBHOOK_SECRET = "segredo-de-teste"
 
 
 class Clock:
@@ -67,6 +69,7 @@ def runtime(session, clock, tmp_path):
         pix_health=InMemoryPixHealth(),
         job_marks=InMemoryJobMarks(),
         documents=LocalDocumentStore(tmp_path / "docs"),
+        webhook_verifier=HmacVerifier(WEBHOOK_SECRET),
         mode="dev",
         clock=clock,
     )
````

Crie `server/tests/api/test_payments_routes.py`:

````python
import json

import pytest

from app.api.webhook import SIGNATURE_HEADER, sign
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.payments import PaymentProviderError
from tests.api.conftest import WEBHOOK_SECRET
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def corrida_aceita(client, pax, rider, metodo="pix"):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    corrida = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": metodo}, headers=pax.headers
    ).json()
    assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers).status_code == 200
    return corrida


def enviar(client, evento, segredo=WEBHOOK_SECRET, corpo=None, cabecalho=SIGNATURE_HEADER):
    corpo = json.dumps(evento).encode() if corpo is None else corpo
    return client.post("/v1/webhooks/pix", content=corpo, headers={cabecalho: sign(segredo, corpo)})


# --- aviso do provedor -----------------------------------------------------------------------


def test_aviso_de_pago_assinado_confirma_a_corrida_e_avisa_os_dois(client, pax, rider, runtime, session, listen):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    avisos_pax, avisos_rider = listen(pax.user_id), listen(rider.user_id)
    resposta = enviar(client, runtime.provider.mark_paid(cobranca))
    assert resposta.status_code == 200 and resposta.json() == {"status": "applied"}
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is True
    assert avisos_pax.types == ["pix_confirmed"] and avisos_rider.types == ["payment_received"]
    assert PgLedger(session).is_balanced() is True


def test_aviso_repetido_nao_cobra_nem_avisa_duas_vezes(client, pax, rider, runtime, session, listen):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    assert enviar(client, evento).json() == {"status": "applied"}
    avisos = listen(pax.user_id)
    assert enviar(client, evento).json() == {"status": "duplicate"}
    assert avisos.messages == []
    assert PgLedger(session).balance(f"rider:{rider.user_id}") == corrida["price_cents"] - 100


@pytest.mark.parametrize(
    "cabecalho, segredo",
    [(SIGNATURE_HEADER, "outro-segredo"), ("x-outra-coisa", WEBHOOK_SECRET)],
)
def test_aviso_com_assinatura_falsa_ou_ausente_e_recusado_sem_mexer_em_nada(
    client, pax, rider, runtime, session, cabecalho, segredo
):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    resposta = enviar(client, evento, segredo=segredo, cabecalho=cabecalho)
    assert resposta.status_code == 401 and resposta.json()["error"]["code"] == "bad_signature"
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is False


def test_corpo_alterado_depois_de_assinado_e_recusado(client, pax, rider, runtime, session):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    original = json.dumps(evento).encode()
    assinatura = sign(WEBHOOK_SECRET, original)
    adulterado = original.replace(b'"amount_cents": ', b'"amount_cents": 1')
    resposta = client.post("/v1/webhooks/pix", content=adulterado, headers={SIGNATURE_HEADER: assinatura})
    assert resposta.status_code == 401


@pytest.mark.parametrize("campo, valor", [("amount_cents", 1), ("ride_id", "ride-de-outro")])
def test_aviso_que_nao_bate_com_a_cobranca_guardada_nao_e_aplicado(
    client, pax, rider, runtime, session, campo, valor
):
    corrida = corrida_aceita(client, pax, rider)
    evento = runtime.provider.mark_paid(repo.get_current_charge_id(session, corrida["ride_id"]))
    resposta = enviar(client, evento | {campo: valor})
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "event_mismatch"
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is False
    assert enviar(client, evento).json() == {"status": "applied"}       # o aviso verdadeiro ainda vale: o id não foi gasto


def test_aviso_de_cobranca_desconhecida_e_confirmado_sem_efeito(client):
    evento = {"event_id": "evt-x", "type": "paid", "charge_id": "ch-fantasma", "ride_id": "ride-x", "amount_cents": 700}
    resposta = enviar(client, evento)
    assert resposta.status_code == 200 and resposta.json() == {"status": "unknown_charge"}


@pytest.mark.parametrize(
    "evento",
    [
        {"event_id": "e", "type": "refunded", "charge_id": "c", "ride_id": "r", "amount_cents": 1},
        {"event_id": "e", "type": "paid", "charge_id": "c", "ride_id": "r", "amount_cents": -5},
        {"event_id": "", "type": "paid", "charge_id": "c", "ride_id": "r", "amount_cents": 5},
        {"type": "paid"},
    ],
)
def test_aviso_mal_formado_e_422_mesmo_com_assinatura_certa(client, evento):
    assert enviar(client, evento).status_code == 422


def test_corpo_que_nao_e_json_e_corpo_gigante(client):
    assert enviar(client, None, corpo=b"isto nao e json").status_code == 422
    assert enviar(client, None, corpo=b"{" + b" " * 70_000 + b"}").status_code == 413


def test_pix_pago_depois_de_cancelar_e_devolvido_e_o_passageiro_e_avisado(
    client, pax, rider, runtime, session, listen
):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    assert client.post(f"/v1/passenger/rides/{corrida['ride_id']}/cancel", headers=pax.headers).status_code == 200
    avisos = listen(pax.user_id)
    assert enviar(client, runtime.provider.mark_paid(cobranca)).json() == {"status": "refunded"}
    assert avisos.types == ["payment_refunded"]
    assert runtime.provider.charges[cobranca].refunded is True


# --- ver a cobrança ------------------------------------------------------------------------------


def test_so_quem_participa_ve_a_cobranca_da_corrida(client, runtime, pax, rider, session):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    esperado = {
        "charge_id": cobranca, "purpose": "ride", "ride_id": corrida["ride_id"],
        "amount_cents": corrida["price_cents"], "paid": False, "br_code": f"fake-pix|{cobranca}|{corrida['price_cents']}",
    }
    assert client.get(f"/v1/charges/{cobranca}", headers=pax.headers).json() == esperado
    assert client.get(f"/v1/charges/{cobranca}", headers=rider.headers).json() == esperado
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    assert client.get(f"/v1/charges/{cobranca}", headers=intruso.headers).status_code == 403
    assert client.get(f"/v1/charges/{cobranca}").status_code == 401
    assert client.get("/v1/charges/nao-existe", headers=pax.headers).status_code == 404


def test_cobranca_da_entrada_e_so_do_motoqueiro(client, runtime, pax, rider):
    entrada = client.post("/v1/rider/entry-charge", headers=rider.headers).json()
    visto = client.get(f"/v1/charges/{entrada['charge_id']}", headers=rider.headers).json()
    assert visto["purpose"] == "entry" and visto["ride_id"] is None and visto["amount_cents"] == 5000
    assert client.get(f"/v1/charges/{entrada['charge_id']}", headers=pax.headers).status_code == 403


# --- provedor fora do ar -----------------------------------------------------------------------


def test_provedor_fora_do_ar_da_503_e_o_app_passa_a_oferecer_so_dinheiro(client, pax, rider, runtime, clock):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    corrida = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "pix"}, headers=pax.headers
    ).json()

    def fora_do_ar(*args, **kwargs):
        raise PaymentProviderError("timeout")

    runtime.provider.create_pix_charge = fora_do_ar
    resposta = client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers)
    assert resposta.status_code == 503 and resposta.json()["error"]["code"] == "payment_unavailable"
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["payment_methods"] == ["cash"]
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["state"] == "searching"
    clock.advance(61)
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["payment_methods"] == ["pix", "cash"]


# --- rotas só de desenvolvimento ----------------------------------------------------------------


def test_rota_de_desenvolvimento_devolve_o_ultimo_codigo_de_login(client, runtime):
    client.post("/v1/auth/code", json={"phone": "75 99999-1234"})
    codigo = runtime.otp_sender.last_code("+5575999991234")
    assert client.get("/v1/dev/otp", params={"phone": "75 99999-1234"}).json() == {"code": codigo}
    assert client.get("/v1/dev/otp", params={"phone": "75 98888-0000"}).status_code == 404


def test_rota_de_desenvolvimento_paga_um_pix_pelo_mesmo_caminho_do_aviso_real(client, pax, rider, session):
    corrida = corrida_aceita(client, pax, rider)
    cobranca = repo.get_current_charge_id(session, corrida["ride_id"])
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "applied"}
    assert repo.get_ride(session, corrida["ride_id"]).pix_paid is True
    assert client.post(f"/v1/dev/pix/{cobranca}/pay").json() == {"status": "duplicate"}
    assert client.post("/v1/dev/pix/ch-fantasma/pay").status_code == 404


def test_fora_do_modo_dev_as_rotas_de_desenvolvimento_nem_existem(runtime):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.api.app import create_app

    producao = dataclasses.replace(runtime, mode="production")
    with TestClient(create_app(producao)) as cliente:
        assert cliente.get("/v1/dev/otp", params={"phone": "75 99999-1234"}).status_code == 404
        assert cliente.post("/v1/dev/pix/ch-1/pay").status_code == 404
        assert cliente.get("/docs").status_code == 404
````

Altere `server/tests/api/test_runtime.py`:

````diff
--- a/server/tests/api/test_runtime.py
+++ b/server/tests/api/test_runtime.py
@@ -144,8 +144,15 @@ def test_modo_de_producao_recusa_subir_com_adaptadores_falsos(settings):
         build_runtime(dataclasses.replace(settings, mode="production"))
 
 
+def test_sem_o_segredo_do_aviso_do_provedor_o_servidor_nao_sobe(settings):
+    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
+        build_runtime(dataclasses.replace(settings, mode="dev", webhook_secret=None))
+
+
 def test_modo_dev_monta_tudo_com_redis_de_verdade(settings, redis_test_url, redis_client):
-    runtime = build_runtime(dataclasses.replace(settings, mode="dev", redis_url=redis_test_url))
+    runtime = build_runtime(
+        dataclasses.replace(settings, mode="dev", redis_url=redis_test_url, webhook_secret="segredo-de-teste")
+    )
     assert isinstance(runtime, Runtime) and runtime.mode == "dev"
     runtime.check()                                   # banco e Redis respondem
     assert runtime.positions.get("ninguem") is None
````

Altere `server/tests/services/test_payment_service.py`:

````diff
--- a/server/tests/services/test_payment_service.py
+++ b/server/tests/services/test_payment_service.py
@@ -271,3 +271,34 @@ def test_espera_na_chegada_esgotada_em_dinheiro_so_cancela_com_compensacao(sessi
     assert service.cancel_after_arrival_timeout(session, "ride-1", now=100 + 300) == CancelResult(200, False)
     assert repo.get_ride(session, "ride-1").state is RideState.CANCELLED
     assert divida(session) == (1000, 0)
+
+
+def test_pix_pago_avisa_o_passageiro_e_o_motoqueiro(session, provider):
+    from app.services.events import EventCollector
+
+    avisos = EventCollector()
+    service = PaymentService(provider, events=avisos)
+    mundo(session)
+    charge = service.start_pix_charge(session, "ride-1", FEE)
+    assert avisos.events == ()                          # criar a cobrança não avisa ninguém
+    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "applied"
+    assert [(e.user_id, e.type, e.payload) for e in avisos.events] == [
+        ("p1", "pix_confirmed", {"ride_id": "ride-1", "amount_cents": 700}),
+        ("r1", "payment_received", {"ride_id": "ride-1", "late": False}),
+    ]
+    service.on_provider_event(session, provider.mark_paid(charge.charge_id))     # aviso repetido
+    assert len(avisos.events) == 2
+
+
+def test_pix_pago_depois_do_cancelamento_avisa_que_o_dinheiro_volta(session, provider):
+    from app.services.events import EventCollector
+
+    avisos = EventCollector()
+    service = PaymentService(provider, events=avisos)
+    mundo(session)
+    charge = service.start_pix_charge(session, "ride-1", FEE)
+    service.cancel_ride(session, "ride-1", now=20)
+    assert service.on_provider_event(session, provider.mark_paid(charge.charge_id)) == "refunded"
+    assert [(e.user_id, e.type, e.payload) for e in avisos.events] == [
+        ("p1", "payment_refunded", {"ride_id": "ride-1", "amount_cents": 700}),
+    ]
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_payments_routes.py tests/api/test_runtime.py tests/services/test_payment_service.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.api.webhook'`.

- [ ] **Step 3: Implementar**

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -9,6 +9,7 @@ from app.api.routes import admin as admin_routes
 from app.api.routes import auth as auth_routes
 from app.api.routes import files as files_routes
 from app.api.routes import passenger as passenger_routes
+from app.api.routes import payments as payments_routes
 from app.api.routes import rider as rider_routes
 from app.api.routes import rides as rides_routes
 
@@ -31,6 +32,12 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     app.include_router(files_routes.router)
     app.include_router(passenger_routes.router)
     app.include_router(rides_routes.router)
+    app.include_router(payments_routes.router)
+
+    if getattr(runtime, "mode", None) == "dev":
+        from app.api.routes import dev as dev_routes
+
+        app.include_router(dev_routes.router)
 
     if runtime is not None:
 
````

Crie `server/app/api/body.py`:

````python
"""Leitura de corpo de pedido com teto de tamanho, mesmo quando o cliente não declara o tamanho."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Request


async def read_limited(request: Request, limit: int, too_big: Callable[[], Exception]) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_big()
        chunks.append(chunk)
    return b"".join(chunks)
````

Altere `server/app/api/errors.py`:

````diff
--- a/server/app/api/errors.py
+++ b/server/app/api/errors.py
@@ -54,9 +54,10 @@ _RULES: dict[type[Exception], _Rule] = {
     WrongPin: _Rule(422, "wrong_pin", "Código errado. Confira os 4 dígitos com o passageiro."),
     RegistrationError: _Rule(422, "invalid"),
     ValueError: _Rule(422, "invalid"),
-    PaymentProviderError: _Rule(503, "payment_unavailable", "O Pix está instável agora. Tente de novo em instantes."),
 }
 
+PIX_DOWN_FOR_S = 60.0
+
 INTERNAL_MESSAGE = "Algo deu errado. Tente de novo."
 
 
@@ -79,6 +80,14 @@ async def _cannot_go_online(request: Request, exc: CannotGoOnline) -> JSONRespon
     return error_response(409, exc.code, exc.message)
 
 
+async def _payment_unavailable(request: Request, exc: PaymentProviderError) -> JSONResponse:
+    # Desde já, e por um minuto, o app passa a oferecer só dinheiro (spec, seção 12).
+    runtime = getattr(request.app.state, "runtime", None)
+    if runtime is not None:
+        runtime.pix_health.mark_down(runtime.clock(), PIX_DOWN_FOR_S)
+    return error_response(503, "payment_unavailable", "O Pix está instável agora. Tente de novo em instantes.")
+
+
 async def _upload_error(request: Request, exc: UploadError) -> JSONResponse:
     return error_response(exc.status, exc.code, exc.message)
 
@@ -119,6 +128,7 @@ def install_error_handlers(app: FastAPI) -> None:
     app.add_exception_handler(ApiError, _api_error)
     app.add_exception_handler(CannotGoOnline, _cannot_go_online)
     app.add_exception_handler(UploadError, _upload_error)
+    app.add_exception_handler(PaymentProviderError, _payment_unavailable)
     app.add_exception_handler(DuplicateRegistration, _duplicate_registration)
     app.add_exception_handler(LookupError, _not_found)
     app.add_exception_handler(RequestValidationError, _validation)
````

Crie `server/app/api/routes/dev.py`:

````python
"""Ajudas só do modo de desenvolvimento (o simulador e os testes à mão usam). Em produção nem existem."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_runtime
from app.api.errors import ApiError
from app.api.webhook import process_pix_event
from app.services.auth import normalize_phone

router = APIRouter(prefix="/v1/dev", tags=["desenvolvimento"])


@router.get("/otp")
def last_otp(phone: str, request: Request) -> dict:
    """O último código de login enviado a um número (no lugar do WhatsApp, que só chega no plano 7)."""
    sender = get_runtime(request).otp_sender
    try:
        return {"code": sender.last_code(normalize_phone(phone))}
    except (StopIteration, AttributeError):
        raise ApiError(404, "not_found", "Nenhum código enviado para este número.") from None


@router.post("/pix/{charge_id}/pay")
def pay_pix(charge_id: str, request: Request) -> dict:
    """Faz de conta que o passageiro pagou o Pix: gera o aviso do provedor falso e o trata como o real."""
    runtime = get_runtime(request)
    try:
        event = runtime.provider.mark_paid(charge_id)
    except (KeyError, AttributeError):
        raise ApiError(404, "not_found", "Cobrança desconhecida.") from None
    return {"status": process_pix_event(runtime, event)}
````

Crie `server/app/api/routes/payments.py`:

````python
"""Aviso do provedor de pagamento e consulta da cobrança (para o app desenhar o QR do Pix)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.api.body import read_limited
from app.api.deps import current_user, get_runtime
from app.api.errors import ApiError
from app.api.webhook import MAX_WEBHOOK_BYTES, PixEvent, process_pix_event
from app.db import repositories as repo
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1", tags=["pagamentos"])


@router.post("/webhooks/pix")
async def pix_webhook(request: Request) -> dict:
    runtime = get_runtime(request)
    body = await read_limited(
        request, MAX_WEBHOOK_BYTES, lambda: ApiError(413, "too_large", "Aviso grande demais.")
    )
    if not runtime.webhook_verifier.verify(request.headers, body):
        raise ApiError(401, "bad_signature", "Assinatura inválida.")
    try:
        event = PixEvent.model_validate_json(body)
    except ValidationError:
        raise ApiError(422, "invalid", "Aviso ilegível.") from None
    return {"status": await run_in_threadpool(process_pix_event, runtime, event.model_dump())}


@router.get("/charges/{charge_id}")
def get_charge(charge_id: str, request: Request, user: AuthUser = Depends(current_user)) -> dict:
    """Quem pode ver: o motoqueiro da cobrança, o passageiro da corrida e o administrador."""

    def work(unit):
        charge = repo.get_charge(unit.session, charge_id)
        allowed = user.role == "admin" or user.user_id == charge.rider_id
        if not allowed and charge.purpose != "entry" and charge.ride_id:
            allowed = repo.get_ride(unit.session, charge.ride_id).passenger_id == user.user_id
        if not allowed:
            raise ApiError(403, "forbidden", "Você não pode ver esta cobrança.")
        return {
            "charge_id": charge.charge_id, "purpose": charge.purpose, "ride_id": charge.ride_id or None,
            "amount_cents": charge.amount_cents, "paid": charge.paid, "br_code": charge.br_code,
        }

    return get_runtime(request).run(work)
````

Altere `server/app/api/routes/rider.py`:

````diff
--- a/server/app/api/routes/rider.py
+++ b/server/app/api/routes/rider.py
@@ -8,6 +8,7 @@ from fastapi import APIRouter, Depends, Request, Response
 from fastapi.concurrency import run_in_threadpool
 from pydantic import BaseModel, Field
 
+from app.api.body import read_limited
 from app.api.deps import get_runtime, rider_user
 from app.api.views import rider_ride_view, rider_state
 from app.db import queries
@@ -74,17 +75,10 @@ def _save_upload(runtime, rider_id: str, kind: str, data: bytes) -> dict:
 @router.put("/documents/{kind}", status_code=201)
 async def upload_document(kind: DocKind, request: Request, user: AuthUser = Depends(rider_user)) -> dict:
     """Recebe a foto crua no corpo do pedido (sem formulário). Corta em 8 MB mesmo sem tamanho declarado."""
-    declared = request.headers.get("content-length", "")
-    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
-        raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
-    chunks: list[bytes] = []
-    total = 0
-    async for chunk in request.stream():
-        total += len(chunk)
-        if total > MAX_UPLOAD_BYTES:
-            raise UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
-        chunks.append(chunk)
-    return await run_in_threadpool(_save_upload, get_runtime(request), user.user_id, kind, b"".join(chunks))
+    data = await read_limited(
+        request, MAX_UPLOAD_BYTES, lambda: UploadError(413, "file_too_large", "A foto é grande demais (máximo 8 MB).")
+    )
+    return await run_in_threadpool(_save_upload, get_runtime(request), user.user_id, kind, data)
 
 
 @router.post("/register", status_code=201)
````

Crie `server/app/api/webhook.py`:

````python
"""Aviso de pagamento do provedor (Pix). Aqui só existe o formato interno e a assinatura HMAC.

O adaptador real da Woovi (plano 7) traduz o aviso dela para este formato e troca a verificação de
assinatura; o resto (conferir valor e corrida, tratar cada aviso uma vez só) já fica pronto.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

from app.api.errors import ApiError
from app.db import repositories as repo

if TYPE_CHECKING:       # só para os tipos: `app.runtime` importa este módulo
    from app.runtime import Runtime

log = logging.getLogger("app.webhook")

SIGNATURE_HEADER = "x-signature"
MAX_WEBHOOK_BYTES = 16 * 1024


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookVerifier(Protocol):
    def verify(self, headers: Mapping[str, str], body: bytes) -> bool: ...


class HmacVerifier:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("o segredo do aviso do provedor não pode ser vazio")
        self.secret = secret

    def verify(self, headers: Mapping[str, str], body: bytes) -> bool:
        received = headers.get(SIGNATURE_HEADER, "")
        return hmac.compare_digest(received.encode(), sign(self.secret, body).encode())


class PixEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    type: Literal["paid"]
    charge_id: str = Field(min_length=1, max_length=40)
    ride_id: str | None = Field(default=None, max_length=40)
    amount_cents: int = Field(gt=0)


def process_pix_event(runtime: "Runtime", event: dict) -> str:
    """Confere o aviso com a cobrança guardada e o aplica. Devolve "applied", "refunded", "duplicate" ou
    "unknown_charge". Valor ou corrida diferentes da cobrança viram erro 409 e **não gastam** o id do aviso."""

    def work(unit):
        try:
            charge = repo.get_charge(unit.session, event["charge_id"])
        except LookupError:
            log.warning("aviso %s de cobrança desconhecida %s", event["event_id"], event["charge_id"])
            return "unknown_charge"
        if charge.amount_cents != event["amount_cents"] or (charge.ride_id or "") != (event.get("ride_id") or ""):
            log.error("aviso %s não bate com a cobrança %s (valor ou corrida)", event["event_id"], charge.charge_id)
            raise ApiError(409, "event_mismatch", "O aviso não confere com a cobrança.")
        return unit.payments.on_provider_event(unit.session, event)

    return runtime.run(work)
````

Altere `server/app/runtime.py`:

````diff
--- a/server/app/runtime.py
+++ b/server/app/runtime.py
@@ -25,6 +25,7 @@ from app.db.config_store import AppConfig, load_app_config
 from app.db.session import make_engine, make_session_factory
 from app.domain.maps import MapsProvider
 from app.domain.payments import PaymentProvider
+from app.api.webhook import HmacVerifier, WebhookVerifier
 from app.infra.documents import DocumentStore, LocalDocumentStore
 from app.infra.redis_store import (
     FactorStore,
@@ -91,6 +92,7 @@ class Runtime:
     pix_health: PixHealth
     job_marks: JobMarks
     documents: DocumentStore
+    webhook_verifier: WebhookVerifier
     mode: str = "production"
     clock: Callable[[], float] = time.time
     redis_client: Any = None
@@ -173,6 +175,8 @@ def build_runtime(settings: Settings) -> Runtime:
             "Os adaptadores reais (Woovi, Google Maps, código por WhatsApp) são do plano 7. "
             "Por enquanto só existe o modo de desenvolvimento: defina APP_MODE=dev em server/.env."
         )
+    if not settings.webhook_secret:
+        raise RuntimeError("falta WEBHOOK_SECRET em server/.env (assina os avisos do provedor de pagamento)")
     client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
     return Runtime(
         session_factory=make_session_factory(make_engine(settings)),
@@ -187,6 +191,7 @@ def build_runtime(settings: Settings) -> Runtime:
         pix_health=RedisPixHealth(client),
         job_marks=RedisJobMarks(client),
         documents=LocalDocumentStore(settings.upload_dir),
+        webhook_verifier=HmacVerifier(settings.webhook_secret),
         mode="dev",
         redis_client=client,
     )
````

Altere `server/app/services/payments.py`:

````diff
--- a/server/app/services/payments.py
+++ b/server/app/services/payments.py
@@ -132,8 +132,11 @@ class PaymentService:
             refund_needed = on_pix_paid(ride) if is_current else True
             if not refund_needed:
                 confirm_charge_debt(acc, charge)
+                self._emit(ride.passenger_id, "pix_confirmed", {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents})
+                self._emit(ride.rider_id, "payment_received", {"ride_id": ride.ride_id, "late": False})
         if refund_needed:
             self._refund(charge, acc, ledger)
+            self._emit(ride.passenger_id, "payment_refunded", {"ride_id": ride.ride_id, "amount_cents": charge.amount_cents})
             outcome = "refunded"
         else:
             outcome = "applied"
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_payments_routes.py tests/api/test_runtime.py tests/services/test_payment_service.py`
Expected: `53 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `616 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): aviso assinado do provedor, cobrança, Pix fora do ar e rotas de desenvolvimento" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 10: Segurança da corrida: parada longa, saída da rota, localização falsa, SOS (migração 0004)

Durante a corrida o servidor guarda o rastro de posições e avalia `app.domain.safety`: parada longa e saída da rota geram um alerta e perguntam ao passageiro se está tudo bem; localização falsa vira registro e aviso ao dono; o SOS vale durante toda a corrida, avisa o contato de emergência e os administradores, e o dono vê e encerra os alertas. Migração 0004.

**Files:**
- Create: `server/app/adapters/fake_notifier.py`
- Modify: `server/app/api/app.py`
- Modify: `server/app/api/errors.py`
- Modify: `server/app/api/routes/admin.py`
- Modify: `server/app/api/routes/rider.py`
- Create: `server/app/api/routes/safety.py`
- Modify: `server/app/db/models.py`
- Modify: `server/app/db/queries.py`
- Create: `server/app/domain/notifier.py`
- Modify: `server/app/domain/safety.py`
- Create: `server/app/infra/safety_store.py`
- Modify: `server/app/runtime.py`
- Create: `server/app/services/safety.py`
- Create: `server/migrations/versions/0004_alertas_de_seguranca.py`
- Test: `server/tests/api/conftest.py` (alterado)
- Test: `server/tests/api/test_safety_routes.py` (novo)
- Test: `server/tests/db/test_migracoes_reversiveis.py` (novo)
- Test: `server/tests/db/test_schema_safety.py` (novo)
- Test: `server/tests/domain/test_safety_api.py` (novo)
- Test: `server/tests/helpers_db.py` (alterado)
- Test: `server/tests/infra/test_safety_store.py` (novo)
- Test: `server/tests/services/test_safety.py` (novo)

**Interfaces:**
- Consumes: `app.domain.safety.evaluate`, `PositionStore`, `repo.get_emergency_contact`, `queries.rider_card`, `TripService` (`NotYourRide`), as rotas de posição e de administrador.
- Produces: `SafetyAlertRow`; `app.infra.safety_store`: `SafetyStore` (`add_sample`, `get_route`, `set_route`, `claim`), `InMemorySafetyStore`, `RedisSafetyStore`; `app.domain.notifier.ContactNotifier` e `app.adapters.fake_notifier.FakeContactNotifier`; `app.services.safety`: `AlertClosed`, `SosResult(alert_id, contact_registered, contact_notified, repeated)`, `SafetyService(store, positions, notifier, events, cfg)` com `on_rider_position(session, ride_id, passenger_id, point, now)`, `answer_ok(...)`, `sos(...)`, `resolve(...)`; `Unit.safety`; `Runtime.safety_store` e `Runtime.notifier`; `queries.admin_ids`, `list_safety_alerts`; rotas `/v1/rides/{id}/sos`, `/v1/rides/{id}/safety/{alert_id}/ok`, `/v1/admin/safety-alerts`; ajudante de teste `add_in_progress_ride`.

- [ ] **Step 1: Escrever os testes que falham**

Altere `server/tests/api/conftest.py`:

````diff
--- a/server/tests/api/conftest.py
+++ b/server/tests/api/conftest.py
@@ -3,6 +3,7 @@ import pytest
 from fastapi.testclient import TestClient
 
 from app.adapters.fake_maps import FakeMaps
+from app.adapters.fake_notifier import FakeContactNotifier
 from app.adapters.fake_otp import FakeOtpSender
 from app.adapters.fake_payments import FakePaymentProvider
 from app.api.app import create_app
@@ -16,6 +17,7 @@ from app.infra.redis_store import (
     InMemoryPositionStore,
     InMemoryRateLimiter,
 )
+from app.infra.safety_store import InMemorySafetyStore
 from app.realtime.hub import Hub
 from app.runtime import Runtime
 
@@ -70,6 +72,8 @@ def runtime(session, clock, tmp_path):
         job_marks=InMemoryJobMarks(),
         documents=LocalDocumentStore(tmp_path / "docs"),
         webhook_verifier=HmacVerifier(WEBHOOK_SECRET),
+        safety_store=InMemorySafetyStore(),
+        notifier=FakeContactNotifier(),
         mode="dev",
         clock=clock,
     )
````

Crie `server/tests/api/test_safety_routes.py`:

````python
import pytest

from app.db import repositories as repo
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


@pytest.fixture()
def admin(client, runtime, session):
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    return login(client, runtime, "75 99999-0000", "admin")


def corrida(client, pax, rider, ate="start"):
    """Corrida em dinheiro levada até `ate`: accept, arrive, start."""
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    pedido = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
    ).json()
    rid = pedido["ride_id"]
    assert client.post(f"/v1/rider/offers/{rid}/accept", headers=rider.headers).status_code == 200
    if ate == "accept":
        return pedido
    client.post(f"/v1/rider/rides/{rid}/arrive", headers=rider.headers)
    client.post(f"/v1/rider/rides/{rid}/helmet", headers=rider.headers)
    assert client.post(f"/v1/rider/rides/{rid}/start", json={"pin": pedido["pin"]}, headers=rider.headers).status_code == 200
    return pedido


def posicao(client, rider, ponto):
    assert client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers).status_code == 204


def parar_por(client, rider, clock, segundos, ponto=None):
    for _ in range(segundos // 4):
        clock.advance(4)
        posicao(client, rider, ponto or pt(500, 3))


def test_moto_parada_na_corrida_pergunta_ao_passageiro_e_ele_responde(client, pax, rider, admin, clock, listen):
    pedido = corrida(client, pax, rider)
    avisos_pax, avisos_admin = listen(pax.user_id), listen(admin.user_id)
    parar_por(client, rider, clock, 200)
    assert avisos_pax.types.count("safety_check") == 1
    pergunta = next(m for m in avisos_pax.messages if m["type"] == "safety_check")["data"]
    assert pergunta["ride_id"] == pedido["ride_id"] and pergunta["kind"] == "stopped"
    assert avisos_admin.types == ["safety_alert"]

    rota = f"/v1/rides/{pedido['ride_id']}/safety/{pergunta['alert_id']}/ok"
    assert client.post(rota, headers=pax.headers).status_code == 204
    repetida = client.post(rota, headers=pax.headers)
    assert repetida.status_code == 409 and repetida.json()["error"]["code"] == "alert_closed"
    assert avisos_admin.types == ["safety_alert", "safety_ok"]


def test_corrida_ainda_nao_iniciada_nao_gera_aviso_automatico(client, pax, rider, clock, listen):
    corrida(client, pax, rider, ate="accept")
    avisos = listen(pax.user_id)
    parar_por(client, rider, clock, 300)
    assert "safety_check" not in avisos.types and avisos.types.count("rider_position") == 75


def test_so_o_passageiro_da_corrida_responde_o_aviso(client, runtime, pax, rider, clock, listen):
    pedido = corrida(client, pax, rider)
    avisos = listen(pax.user_id)
    parar_por(client, rider, clock, 200)
    alerta = next(m for m in avisos.messages if m["type"] == "safety_check")["data"]["alert_id"]
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    rota = f"/v1/rides/{pedido['ride_id']}/safety/{alerta}/ok"
    assert client.post(rota, headers=intruso.headers).status_code == 403
    assert client.post(rota, headers=rider.headers).status_code == 403
    assert client.post(rota).status_code == 401
    assert client.post(f"/v1/rides/{pedido['ride_id']}/safety/999999/ok", headers=pax.headers).status_code == 404


def test_sos_avisa_o_contato_e_os_administradores_e_aparece_na_lista(client, runtime, pax, rider, admin, listen):
    client.put("/v1/passenger/emergency-contact", json={"name": "Maria", "phone": "75 98888-7777"}, headers=pax.headers)
    pedido = corrida(client, pax, rider)
    posicao(client, rider, pt(700, 20))
    avisos_pax, avisos_admin = listen(pax.user_id), listen(admin.user_id)

    resposta = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo == {
        "alert_id": corpo["alert_id"], "contact_registered": True, "contact_notified": True,
        "repeated": False, "emergency_number": "190",
    }
    [(telefone, texto)] = runtime.notifier.sent
    assert telefone == "+5575988887777" and "Ana Lima" in texto and "ABC0001" in texto
    assert avisos_pax.types == ["sos_sent"] and avisos_admin.types == ["sos"]

    lista = client.get("/v1/admin/safety-alerts", params={"status": "sos"}, headers=admin.headers).json()
    assert [(a["alert_id"], a["kind"], a["passenger_name"], a["plate"]) for a in lista] == [
        (corpo["alert_id"], "sos", "Ana Lima", "ABC0001")
    ]
    assert lista[0]["lat"] == pytest.approx(pt(700, 20).lat, abs=1e-5)
    assert client.get("/v1/admin/safety-alerts", headers=admin.headers).json() == []         # "open" está vazio

    assert client.post(
        f"/v1/admin/safety-alerts/{corpo['alert_id']}/resolve", json={"note": "Liguei, tudo bem."}, headers=admin.headers
    ).status_code == 204
    resolvidos = client.get("/v1/admin/safety-alerts", params={"status": "resolved"}, headers=admin.headers).json()
    assert resolvidos[0]["note"] == "Liguei, tudo bem."
    again = client.post(f"/v1/admin/safety-alerts/{corpo['alert_id']}/resolve", json={}, headers=admin.headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "alert_closed"


def test_sos_funciona_a_caminho_mesmo_sem_contato_e_nao_repete(client, runtime, pax, rider):
    pedido = corrida(client, pax, rider, ate="accept")
    primeiro = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers).json()
    assert (primeiro["contact_registered"], primeiro["contact_notified"], primeiro["repeated"]) == (False, False, False)
    segundo = client.post(f"/v1/rides/{pedido['ride_id']}/sos", headers=pax.headers).json()
    assert segundo["repeated"] is True and segundo["alert_id"] == primeiro["alert_id"]
    assert runtime.notifier.sent == []


def test_sos_fora_da_corrida_ou_de_outra_pessoa(client, runtime, pax, rider):
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    procurando = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
    ).json()
    resposta = client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=pax.headers)
    assert resposta.status_code == 409 and resposta.json()["error"]["code"] == "invalid_state"
    intruso = login(client, runtime, "75 99999-0005", "passenger")
    assert client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=intruso.headers).status_code == 403
    assert client.post(f"/v1/rides/{procurando['ride_id']}/sos", headers=rider.headers).status_code == 403
    assert client.post("/v1/rides/nao-existe/sos", headers=pax.headers).status_code == 404


def test_lista_e_encerramento_de_alertas_sao_so_do_administrador(client, pax, rider):
    for metodo, url in (("get", "/v1/admin/safety-alerts"), ("post", "/v1/admin/safety-alerts/1/resolve")):
        for quem in (pax, rider):
            assert getattr(client, metodo)(url, headers=quem.headers).status_code == 403
        assert getattr(client, metodo)(url).status_code == 401
    assert client.get("/v1/admin/safety-alerts", params={"status": "perdido"}, headers=rider.headers).status_code == 403
````

Crie `server/tests/db/test_migracoes_reversiveis.py`:

````python
"""Cada migração nova precisa desfazer e refazer sem erro (num esquema temporário só deste teste)."""
import uuid

from alembic import command
from sqlalchemy import create_engine, text

from tests.conftest import _alembic_config


def test_migracoes_do_0002_ao_topo_desfazem_e_refazem(settings):
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema},public"})
    config = _alembic_config()
    try:
        for passo, destino in ((command.upgrade, "head"), (command.downgrade, "0002"), (command.upgrade, "head")):
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                config.attributes["schema"] = schema
                passo(config, destino)
        with engine.connect() as conn:
            assert conn.execute(text("select to_regclass(:name)"), {"name": f'"{schema}".safety_alerts'}).scalar()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
````

Crie `server/tests/db/test_schema_safety.py`:

````python
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import RideRow, SafetyAlertRow
from tests.helpers_db import add_passenger, add_rider


def _corrida(session):
    add_passenger(session)
    add_rider(session)
    session.add(
        RideRow(id="ride-1", passenger_id="p1", rider_id="r1", price_cents=700, payment_method="cash", pin="1234", state="in_progress")
    )
    session.flush()


def test_alerta_de_seguranca_guarda_o_que_aconteceu_e_a_resposta(session):
    _corrida(session)
    session.add(SafetyAlertRow(ride_id="ride-1", kind="stopped", lat=-12.96, lng=-39.26, created_at=100.0))
    session.flush()
    alerta = session.query(SafetyAlertRow).one()
    assert (alerta.status, alerta.suspected_mock, alerta.answered_at, alerta.resolved_at) == ("open", False, None, None)


@pytest.mark.parametrize("campo, valor", [("kind", "invasao"), ("status", "perdido")])
def test_tipo_e_situacao_do_alerta_so_aceitam_os_valores_conhecidos(session, campo, valor):
    _corrida(session)
    dados = dict(ride_id="ride-1", kind="stopped", status="open", created_at=1.0) | {campo: valor}
    with pytest.raises(IntegrityError):
        session.add(SafetyAlertRow(**dados))
        session.flush()
````

Crie `server/tests/domain/test_safety_api.py`:

````python
from app.domain.safety import PositionSample, evaluate
from tests.helpers import pt


def test_sem_rota_conhecida_so_o_aviso_de_parada_vale():
    longe = [PositionSample(pt(1000 + 100 * i, 0), 4.0 * i) for i in range(5)]
    assert evaluate(longe, []).alert is None                       # antes estourava: "a rota está vazia"
    parado = [PositionSample(pt(5, 0), 4.0 * i) for i in range(60)]
    assert evaluate(parado, []).alert is not None
````

Altere `server/tests/helpers_db.py`:

````diff
--- a/server/tests/helpers_db.py
+++ b/server/tests/helpers_db.py
@@ -129,3 +129,31 @@ def add_completed_ride(
     ride.fee_cents = fee
     repo.add_ride(session, ride)
     return ride
+
+
+def add_in_progress_ride(
+    session,
+    ride_id: str = "ride-1",
+    passenger_id: str = "p1",
+    rider_id: str = "r1",
+    method: PaymentMethod = PaymentMethod.CASH,
+    route: tuple[tuple[float, float], ...] = (),
+    pickup: GeoPoint = ORIGIN,
+    destination: GeoPoint | None = None,
+) -> Ride:
+    """Corrida já iniciada (código dito, capacete confirmado). A rota esperada vai nos detalhes."""
+    ride = Ride(ride_id, passenger_id, 700, method, pin="4821")
+    start_search(ride, 0)
+    accept(ride, rider_id, 1, rider_busy=False)
+    mark_arrived(ride, 2)
+    confirm_helmet(ride)
+    if method is PaymentMethod.PIX:
+        ride.pix_paid = True
+    start_ride(ride, "4821")
+    ride.fee_cents = 100
+    repo.add_ride(session, ride)
+    repo.set_ride_details(
+        session, ride_id,
+        repo.RideDetails(pickup, destination or pt(1500, 0), "Rua A", "Feira livre", 1950, 1.0, "Preço normal.", route=route),
+    )
+    return ride
````

Crie `server/tests/infra/test_safety_store.py`:

````python
import pytest

from app.domain.geo import GeoPoint
from app.domain.safety import PositionSample
from app.infra.safety_store import InMemorySafetyStore, RedisSafetyStore
from tests.helpers import pt


@pytest.fixture(params=["memoria", "redis"])
def store(request, redis_client):
    return InMemorySafetyStore() if request.param == "memoria" else RedisSafetyStore(redis_client)


def test_guarda_as_posicoes_na_ordem_e_so_as_ultimas(store):
    for i in range(5):
        amostras = store.add_sample("ride-1", PositionSample(pt(10 * i, 0), 100.0 + i), max_samples=3)
    assert [a.t for a in amostras] == [102.0, 103.0, 104.0]
    assert amostras[-1].point.lat == pytest.approx(pt(40, 0).lat)
    assert [a.t for a in store.add_sample("ride-2", PositionSample(pt(0, 0), 1.0), max_samples=3)] == [1.0]


def test_rota_nunca_vista_e_none_e_rota_vazia_tambem_e_lembrada(store):
    assert store.get_route("ride-1") is None
    store.set_route("ride-1", [])
    assert store.get_route("ride-1") == []
    store.set_route("ride-2", [GeoPoint(-12.96, -39.26), GeoPoint(-12.95, -39.25)])
    assert store.get_route("ride-2") == [GeoPoint(-12.96, -39.26), GeoPoint(-12.95, -39.25)]


def test_aviso_so_sai_uma_vez_por_periodo(store):
    assert store.claim("ride-1:stopped", now=1000.0, cooldown_s=600.0) is True
    assert store.claim("ride-1:stopped", now=1100.0, cooldown_s=600.0) is False
    assert store.claim("ride-1:off_route", now=1100.0, cooldown_s=600.0) is True       # outro tipo, outra conta
    assert store.claim("ride-1:stopped", now=1601.0, cooldown_s=600.0) is True         # passou o prazo
````

Crie `server/tests/services/test_safety.py`:

````python
import pytest
from sqlalchemy import select

from app.adapters.fake_notifier import FakeContactNotifier
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import RideRow, SafetyAlertRow, UserRow
from app.domain.config import SafetyConfig
from app.domain.geo import GeoPoint
from app.domain.rides import InvalidTransition
from app.infra.redis_store import InMemoryPositionStore
from app.infra.safety_store import InMemorySafetyStore
from app.services.events import EventCollector
from app.services.safety import AlertClosed, SafetyService
from app.services.trips import NotYourRide
from tests.helpers import ORIGIN, pt
from tests.helpers_db import add_in_progress_ride, add_passenger, add_rider

AGORA = 1_800_000_000.0
ROTA = ((ORIGIN.lat, ORIGIN.lng), (pt(1500, 0).lat, pt(1500, 0).lng))


@pytest.fixture()
def store():
    return InMemorySafetyStore()


@pytest.fixture()
def notifier():
    return FakeContactNotifier()


@pytest.fixture()
def events():
    return EventCollector()


@pytest.fixture()
def positions():
    return InMemoryPositionStore()


@pytest.fixture()
def safety(store, positions, notifier, events):
    return SafetyService(store, positions, notifier, events, AppConfig.defaults())


@pytest.fixture()
def mundo(session):
    add_passenger(session)
    add_rider(session)
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    repo.add_user(session, user_id="adm-2", phone="+5575999990001", name="Sócia", role="admin")
    add_in_progress_ride(session, route=ROTA)


def posicoes(safety, session, pontos, inicio=AGORA, passo=4.0):
    """Manda uma posição por vez, a cada `passo` segundos, e devolve os alertas criados."""
    criados = []
    for i, ponto in enumerate(pontos):
        alerta = safety.on_rider_position(session, "ride-1", "p1", ponto, inicio + i * passo)
        if alerta is not None:
            criados.append(alerta)
    return criados


def tipos(events, user_id):
    return [e.type for e in events.events if e.user_id == user_id]


def test_moto_andando_na_rota_nao_gera_alerta(safety, session, mundo, events):
    caminho = [pt(10 * i, 0) for i in range(60)]
    assert posicoes(safety, session, caminho) == []
    assert session.execute(select(SafetyAlertRow)).first() is None and events.events == ()


def test_parada_longa_pergunta_ao_passageiro_e_avisa_os_administradores(safety, session, mundo, events):
    criados = posicoes(safety, session, [pt(500, 3)] * 50)           # 200 s no mesmo lugar
    assert len(criados) == 1
    alerta = session.execute(select(SafetyAlertRow)).scalar_one()
    assert (alerta.kind, alerta.status, alerta.ride_id, alerta.suspected_mock) == ("stopped", "open", "ride-1", False)
    assert (alerta.lat, alerta.lng) == pytest.approx((pt(500, 3).lat, pt(500, 3).lng))
    pergunta = next(e for e in events.events if e.type == "safety_check")
    assert pergunta.user_id == "p1" and pergunta.payload == {"ride_id": "ride-1", "alert_id": alerta.id, "kind": "stopped"}
    for admin in ("adm-1", "adm-2"):
        aviso = next(e for e in events.events if e.user_id == admin)
        assert aviso.type == "safety_alert" and aviso.payload["alert_id"] == alerta.id
        assert aviso.payload["kind"] == "stopped" and aviso.payload["ride_id"] == "ride-1"


def test_o_mesmo_aviso_nao_repete_dentro_do_prazo_e_volta_depois(safety, session, mundo):
    parado = [pt(500, 3)] * 200                                       # 800 s parado
    posicoes(safety, session, parado[:100])
    assert session.query(SafetyAlertRow).count() == 1                  # 400 s: um aviso só
    posicoes(safety, session, parado[100:], inicio=AGORA + 400)
    assert session.query(SafetyAlertRow).count() == 2                  # passou os 600 s do primeiro


def test_sair_da_rota_so_vale_depois_de_confirmado(safety, session, mundo):
    fora = [pt(500, 400)] * 3                                          # 400 m para o lado, longe dos 300 m
    assert len(posicoes(safety, session, fora[:2])) == 0
    assert len(posicoes(safety, session, fora[2:], inicio=AGORA + 8)) == 1
    assert session.execute(select(SafetyAlertRow.kind)).scalar_one() == "off_route"


def test_a_rota_vem_do_banco_na_primeira_posicao_e_fica_na_memoria(safety, session, mundo, store):
    assert store.get_route("ride-1") is None
    safety.on_rider_position(session, "ride-1", "p1", pt(10, 0), AGORA)
    assert store.get_route("ride-1") == [GeoPoint(*ponto) for ponto in ROTA]
    session.get(RideRow, "ride-1").route = None
    session.flush()
    safety.on_rider_position(session, "ride-1", "p1", pt(20, 0), AGORA + 4)
    assert store.get_route("ride-1") == [GeoPoint(*ponto) for ponto in ROTA]      # não leu de novo


def test_corrida_sem_rota_guardada_so_avisa_parada(safety, session, store):
    add_passenger(session)
    add_rider(session)
    add_in_progress_ride(session)                                       # sem rota
    assert safety.on_rider_position(session, "ride-1", "p1", pt(9000, 9000), AGORA) is None
    assert store.get_route("ride-1") == []
    longe = [pt(9000 + 100 * i, 9000) for i in range(5)]
    assert posicoes(safety, session, longe, inicio=AGORA + 4) == []


def test_localizacao_falsa_suspeita_vira_registro_da_corrida_e_aviso_uma_vez_so(safety, session, mundo, events):
    pulos = [pt(0, 0), pt(80_000, 0), pt(10, 0), pt(80_000, 0), pt(20, 0), pt(30, 0)]
    posicoes(safety, session, pulos)
    posicoes(safety, session, [pt(40, 0), pt(50, 0)], inicio=AGORA + 100)          # continua suspeito
    assert [kind for kind, _ in repo.ride_events(session, "ride-1")].count("mock_location_suspected") == 1
    assert sum(1 for e in events.events if e.type == "mock_location_suspected") == 2    # um para cada administrador


def test_passageiro_responde_que_esta_tudo_bem(safety, session, mundo, events):
    alerta = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    safety.answer_ok(session, "p1", "ride-1", alerta.id, AGORA + 300)
    session.expire_all()
    guardado = session.get(SafetyAlertRow, alerta.id)
    assert (guardado.status, guardado.answered_at) == ("ok", AGORA + 300)
    assert "safety_ok" in tipos(events, "adm-1")
    with pytest.raises(AlertClosed):
        safety.answer_ok(session, "p1", "ride-1", alerta.id, AGORA + 301)


def test_so_o_passageiro_da_corrida_responde_e_o_aviso_tem_que_ser_dela(safety, session, mundo):
    alerta = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    add_passenger(session, "p2", "+5575900000010")
    with pytest.raises(NotYourRide):
        safety.answer_ok(session, "p2", "ride-1", alerta.id, AGORA + 300)
    with pytest.raises(LookupError):
        safety.answer_ok(session, "p1", "ride-1", 999_999, AGORA + 300)
    with pytest.raises(LookupError):
        safety.answer_ok(session, "p1", "ride-outra", alerta.id, AGORA + 300)


# --- SOS ------------------------------------------------------------------------------------------


def com_contato(session):
    repo.set_emergency_contact(session, "p1", "Maria", "+5575988887777")


def test_sos_avisa_o_contato_os_administradores_e_o_proprio_passageiro(safety, session, mundo, positions, notifier, events):
    com_contato(session)
    positions.update("r1", pt(700, 20), AGORA)
    resultado = safety.sos(session, "p1", "ride-1", AGORA + 10)
    assert resultado.contact_registered is True and resultado.contact_notified is True and resultado.repeated is False
    alerta = session.execute(select(SafetyAlertRow)).scalar_one()
    assert (alerta.kind, alerta.status) == ("sos", "sos") and alerta.id == resultado.alert_id
    assert (alerta.lat, alerta.lng) == pytest.approx((pt(700, 20).lat, pt(700, 20).lng))
    [(telefone, texto)] = notifier.sent
    assert telefone == "+5575988887777" and "Passageiro p1" in texto and "AAA1A11" in texto
    assert f"https://maps.google.com/?q={pt(700, 20).lat:.6f},{pt(700, 20).lng:.6f}" in texto
    assert tipos(events, "adm-1") == ["sos"] and tipos(events, "adm-2") == ["sos"]
    enviado = next(e for e in events.events if e.type == "sos_sent")
    assert enviado.user_id == "p1" and enviado.payload["contact_notified"] is True


def test_sos_sem_contato_cadastrado_continua_valendo(safety, session, mundo, notifier):
    resultado = safety.sos(session, "p1", "ride-1", AGORA)
    assert (resultado.contact_registered, resultado.contact_notified) == (False, False)
    assert notifier.sent == [] and session.query(SafetyAlertRow).count() == 1


def test_falha_ao_avisar_o_contato_nao_impede_o_sos(safety, session, mundo, notifier):
    com_contato(session)
    notifier.fail = True
    resultado = safety.sos(session, "p1", "ride-1", AGORA)
    assert (resultado.contact_registered, resultado.contact_notified) == (True, False)
    assert session.execute(select(SafetyAlertRow.note)).scalar_one() == "falha ao avisar o contato"


def test_sos_apertado_de_novo_nao_avisa_o_contato_outra_vez(safety, session, mundo, notifier):
    com_contato(session)
    primeiro = safety.sos(session, "p1", "ride-1", AGORA)
    segundo = safety.sos(session, "p1", "ride-1", AGORA + 30)
    assert segundo.repeated is True and segundo.alert_id == primeiro.alert_id
    assert len(notifier.sent) == 1 and session.query(SafetyAlertRow).count() == 1
    terceiro = safety.sos(session, "p1", "ride-1", AGORA + 400)           # passou o prazo: avisa de novo
    assert terceiro.repeated is False and len(notifier.sent) == 2


def test_sos_leva_junto_o_aviso_aberto_da_corrida(safety, session, mundo):
    aberto = posicoes(safety, session, [pt(500, 3)] * 50)[0]
    resultado = safety.sos(session, "p1", "ride-1", AGORA + 300)
    session.expire_all()
    assert session.get(SafetyAlertRow, aberto.id).status == "sos"
    assert resultado.alert_id != aberto.id


def test_sos_so_durante_a_corrida_e_so_do_proprio_passageiro(safety, session, mundo):
    add_passenger(session, "p2", "+5575900000010")
    with pytest.raises(NotYourRide):
        safety.sos(session, "p2", "ride-1", AGORA)
    with pytest.raises(LookupError):
        safety.sos(session, "p1", "ride-x", AGORA)
    ride = repo.get_ride(session, "ride-1", for_update=True)
    ride.state = type(ride.state).COMPLETED
    repo.save_ride(session, ride)
    with pytest.raises(InvalidTransition):
        safety.sos(session, "p1", "ride-1", AGORA)


# --- administrador ----------------------------------------------------------------------------------


def test_administrador_encerra_o_alerta_com_uma_anotacao(safety, session, mundo):
    alerta = safety.sos(session, "p1", "ride-1", AGORA)
    safety.resolve(session, alerta.alert_id, "adm-1", "Liguei, estava tudo certo.", AGORA + 600)
    session.expire_all()
    guardado = session.get(SafetyAlertRow, alerta.alert_id)
    assert (guardado.status, guardado.resolved_by, guardado.resolved_at, guardado.note) == (
        "resolved", "adm-1", AGORA + 600, "Liguei, estava tudo certo.",
    )
    with pytest.raises(AlertClosed):
        safety.resolve(session, alerta.alert_id, "adm-2", "", AGORA + 700)
    with pytest.raises(LookupError):
        safety.resolve(session, 999_999, "adm-1", "", AGORA)


def test_limites_vem_da_configuracao(session, mundo, store, positions, notifier, events):
    cfg = AppConfig.defaults()
    cfg = AppConfig(cfg.pricing, cfg.fees, cfg.rides, cfg.dispatch, SafetyConfig(stopped_after_s=30, alert_cooldown_s=60))
    rapido = SafetyService(store, positions, notifier, events, cfg)
    assert len(posicoes(rapido, session, [pt(500, 3)] * 12)) == 1          # 44 s já basta
    assert session.get(UserRow, "p1") is not None
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q \
  tests/api/test_safety_routes.py \
  tests/db/test_migracoes_reversiveis.py \
  tests/db/test_schema_safety.py \
  tests/domain/test_safety_api.py \
  tests/infra/test_safety_store.py \
  tests/services/test_safety.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.adapters.fake_notifier'`.

- [ ] **Step 3: Implementar**

Crie `server/app/adapters/fake_notifier.py`:

````python
"""Aviso ao contato de emergência falso, para testes e para o servidor de desenvolvimento."""
from __future__ import annotations

import logging

log = logging.getLogger("app.notifier")


class FakeContactNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False           # os testes ligam para simular o WhatsApp fora do ar

    def notify(self, phone: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("canal de aviso fora do ar")
        self.sent.append((phone, text))
        del self.sent[:-200]
        log.info("aviso para %s: %s", phone, text)
````

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -12,6 +12,7 @@ from app.api.routes import passenger as passenger_routes
 from app.api.routes import payments as payments_routes
 from app.api.routes import rider as rider_routes
 from app.api.routes import rides as rides_routes
+from app.api.routes import safety as safety_routes
 
 
 def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
@@ -33,6 +34,7 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     app.include_router(passenger_routes.router)
     app.include_router(rides_routes.router)
     app.include_router(payments_routes.router)
+    app.include_router(safety_routes.router)
 
     if getattr(runtime, "mode", None) == "dev":
         from app.api.routes import dev as dev_routes
````

Altere `server/app/api/errors.py`:

````diff
--- a/server/app/api/errors.py
+++ b/server/app/api/errors.py
@@ -20,6 +20,7 @@ from app.services.auth import TooManyRequests
 from app.services.dispatch import OfferGone
 from app.services.quotes import NotAllowed, QuoteExpired
 from app.services.riders import CannotGoOnline, DuplicateRegistration, InvalidState, RegistrationError
+from app.services.safety import AlertClosed
 from app.services.trips import AlreadyRated, NotYourRide
 
 
@@ -49,6 +50,7 @@ _RULES: dict[type[Exception], _Rule] = {
     OfferGone: _Rule(409, "offer_gone"),
     NotYourRide: _Rule(403, "not_your_ride"),
     AlreadyRated: _Rule(409, "already_rated"),
+    AlertClosed: _Rule(409, "alert_closed"),
     InvalidTransition: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual da corrida."),
     InvalidState: _Rule(409, "invalid_state", "Essa ação não vale para o estado atual do cadastro."),
     WrongPin: _Rule(422, "wrong_pin", "Código errado. Confira os 4 dígitos com o passageiro."),
````

Altere `server/app/api/routes/admin.py`:

````diff
--- a/server/app/api/routes/admin.py
+++ b/server/app/api/routes/admin.py
@@ -17,6 +17,10 @@ class ReasonIn(BaseModel):
     reason: str = Field(min_length=1, max_length=200)
 
 
+class NoteIn(BaseModel):
+    note: str = Field(default="", max_length=200)
+
+
 def _rider_item(item: queries.RiderListItem) -> dict:
     return {
         "rider_id": item.rider_id, "name": item.name, "phone": item.phone, "cpf": item.cpf, "plate": item.plate,
@@ -61,3 +65,33 @@ def block(rider_id: str, body: ReasonIn, request: Request, admin: AuthUser = Dep
 def unblock(rider_id: str, request: Request, admin: AuthUser = Depends(admin_user)) -> Response:
     get_runtime(request).run(lambda unit: unit.riders.unblock(unit.session, rider_id))
     return Response(status_code=204)
+
+
+@router.get("/safety-alerts")
+def list_safety_alerts(
+    request: Request,
+    status: Literal["open", "ok", "sos", "resolved"] = "open",
+    limit: int = Query(50, ge=1, le=200),
+    offset: int = Query(0, ge=0),
+    admin: AuthUser = Depends(admin_user),
+) -> list[dict]:
+    items = get_runtime(request).run(lambda unit: queries.list_safety_alerts(unit.session, status, limit, offset))
+    return [
+        {
+            "alert_id": i.alert_id, "ride_id": i.ride_id, "kind": i.kind, "status": i.status,
+            "suspected_mock": i.suspected_mock, "lat": i.lat, "lng": i.lng, "created_at": i.created_at,
+            "answered_at": i.answered_at, "resolved_at": i.resolved_at, "note": i.note,
+            "passenger_name": i.passenger_name, "rider_name": i.rider_name, "plate": i.plate,
+        }
+        for i in items
+    ]
+
+
+@router.post("/safety-alerts/{alert_id}/resolve", status_code=204)
+def resolve_safety_alert(
+    alert_id: int, body: NoteIn, request: Request, admin: AuthUser = Depends(admin_user)
+) -> Response:
+    get_runtime(request).run(
+        lambda unit: unit.safety.resolve(unit.session, alert_id, admin.user_id, body.note, unit.now)
+    )
+    return Response(status_code=204)
````

Altere `server/app/api/routes/rider.py`:

````diff
--- a/server/app/api/routes/rider.py
+++ b/server/app/api/routes/rider.py
@@ -140,11 +140,14 @@ def report_position(body: PositionIn, request: Request, user: AuthUser = Depends
         context = queries.rider_context(unit.session, user.user_id)
         if context is None or not context.online:
             return
-        unit.riders.report_position(user.user_id, GeoPoint(body.lat, body.lng), unit.now)
+        point = GeoPoint(body.lat, body.lng)
+        unit.riders.report_position(user.user_id, point, unit.now)
         if context.ride_id is not None and context.ride_state in _ON_THE_MOVE:
             unit.events.add(
                 context.passenger_id, "rider_position", {"ride_id": context.ride_id, "lat": body.lat, "lng": body.lng}
             )
+            if context.ride_state == "in_progress":
+                unit.safety.on_rider_position(unit.session, context.ride_id, context.passenger_id, point, unit.now)
 
     get_runtime(request).run(work)
     return Response(status_code=204)
````

Crie `server/app/api/routes/safety.py`:

````python
"""SOS e resposta ao aviso de segurança, do lado do passageiro."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_runtime, passenger_user
from app.services.auth import AuthUser

router = APIRouter(prefix="/v1/rides", tags=["segurança"])


@router.post("/{ride_id}/sos")
def sos(ride_id: str, request: Request, user: AuthUser = Depends(passenger_user)) -> dict:
    """Vale durante toda a corrida, não só depois de um aviso. O app liga para o 190; aqui avisamos o resto."""
    result = get_runtime(request).run(lambda unit: unit.safety.sos(unit.session, user.user_id, ride_id, unit.now))
    return {
        "alert_id": result.alert_id, "contact_registered": result.contact_registered,
        "contact_notified": result.contact_notified, "repeated": result.repeated, "emergency_number": "190",
    }


@router.post("/{ride_id}/safety/{alert_id}/ok", status_code=204)
def safety_ok(ride_id: str, alert_id: int, request: Request, user: AuthUser = Depends(passenger_user)) -> Response:
    get_runtime(request).run(
        lambda unit: unit.safety.answer_ok(unit.session, user.user_id, ride_id, alert_id, unit.now)
    )
    return Response(status_code=204)
````

Altere `server/app/db/models.py`:

````diff
--- a/server/app/db/models.py
+++ b/server/app/db/models.py
@@ -260,6 +260,29 @@ class RideEventRow(Base):
     created_at: Mapped[float] = mapped_column(Float(53))
 
 
+class SafetyAlertRow(Base):
+    __tablename__ = "safety_alerts"
+    __table_args__ = (
+        CheckConstraint("kind IN ('stopped','off_route','sos')", name="alert_kind_valid"),
+        CheckConstraint("status IN ('open','ok','sos','resolved')", name="alert_status_valid"),
+        Index("ix_safety_alerts_status", "status"),
+        Index("ix_safety_alerts_ride_id", "ride_id"),
+    )
+
+    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
+    ride_id: Mapped[str] = mapped_column(String(40), ForeignKey("rides.id"))
+    kind: Mapped[str] = mapped_column(String(10))
+    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
+    suspected_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
+    lat: Mapped[float | None] = mapped_column(Float(53), nullable=True)
+    lng: Mapped[float | None] = mapped_column(Float(53), nullable=True)
+    created_at: Mapped[float] = mapped_column(Float(53))
+    answered_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
+    resolved_at: Mapped[float | None] = mapped_column(Float(53), nullable=True)
+    resolved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
+    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
+
+
 class RatingRow(Base):
     __tablename__ = "ratings"
     __table_args__ = (
````

Altere `server/app/db/queries.py`:

````diff
--- a/server/app/db/queries.py
+++ b/server/app/db/queries.py
@@ -4,9 +4,9 @@ from __future__ import annotations
 from dataclasses import dataclass
 
 from sqlalchemy import func, select
-from sqlalchemy.orm import Session
+from sqlalchemy.orm import Session, aliased
 
-from app.db.models import RideOfferRow, RideRow, RiderProfileRow, UserRow
+from app.db.models import RideOfferRow, RideRow, RiderProfileRow, SafetyAlertRow, UserRow
 from app.domain.fees import RiderAccount
 from app.domain.geo import GeoPoint
 from app.domain.rides import RideState
@@ -360,3 +360,52 @@ def rider_context(session: Session, rider_id: str) -> RiderContext | None:
         .limit(1)
     ).first()
     return RiderContext(bool(online), *(tuple(ride) if ride else (None, None, None)))
+
+
+def admin_ids(session: Session) -> list[str]:
+    """Quem recebe os avisos de segurança: todos os administradores sem bloqueio."""
+    return list(
+        session.execute(
+            select(UserRow.id).where(UserRow.role == "admin", UserRow.is_blocked.is_(False)).order_by(UserRow.id)
+        ).scalars()
+    )
+
+
+@dataclass(frozen=True)
+class SafetyAlertItem:
+    alert_id: int
+    ride_id: str
+    kind: str
+    status: str
+    suspected_mock: bool
+    lat: float | None
+    lng: float | None
+    created_at: float
+    answered_at: float | None
+    resolved_at: float | None
+    note: str | None
+    passenger_name: str
+    rider_name: str
+    plate: str
+
+
+def list_safety_alerts(session: Session, status: str, limit: int, offset: int) -> list[SafetyAlertItem]:
+    passenger, rider = aliased(UserRow), aliased(UserRow)
+    rows = session.execute(
+        select(SafetyAlertRow, passenger.name, rider.name, RiderProfileRow.plate)
+        .join(RideRow, RideRow.id == SafetyAlertRow.ride_id)
+        .join(passenger, passenger.id == RideRow.passenger_id)
+        .join(rider, rider.id == RideRow.rider_id)
+        .join(RiderProfileRow, RiderProfileRow.user_id == RideRow.rider_id)
+        .where(SafetyAlertRow.status == status)
+        .order_by(SafetyAlertRow.created_at.desc(), SafetyAlertRow.id.desc())
+        .limit(limit)
+        .offset(offset)
+    ).all()
+    return [
+        SafetyAlertItem(
+            a.id, a.ride_id, a.kind, a.status, a.suspected_mock, a.lat, a.lng, a.created_at, a.answered_at,
+            a.resolved_at, a.note, passenger_name, rider_name, plate,
+        )
+        for a, passenger_name, rider_name, plate in rows
+    ]
````

Crie `server/app/domain/notifier.py`:

````python
"""Aviso a uma pessoa de fora do app (o contato de emergência do passageiro). O WhatsApp real é do plano 7."""
from __future__ import annotations

from typing import Protocol


class ContactNotifier(Protocol):
    def notify(self, phone: str, text: str) -> None: ...
````

Altere `server/app/domain/safety.py`:

````diff
--- a/server/app/domain/safety.py
+++ b/server/app/domain/safety.py
@@ -99,6 +99,6 @@ def evaluate(
     suspected = jumps >= cfg.mock_location_jumps
     if is_stopped_too_long(good, cfg):
         return SafetyResult(AlertType.STOPPED, suspected)
-    if is_off_route(good, route, cfg):
+    if route and is_off_route(good, route, cfg):      # sem rota guardada, só o aviso de parada vale
         return SafetyResult(AlertType.OFF_ROUTE, suspected)
     return SafetyResult(None, suspected)
````

Crie `server/app/infra/safety_store.py`:

````python
"""Rastro curto de posições da corrida em andamento, rota esperada e controle de avisos repetidos.

Fica no Redis porque muda a cada 4 segundos e só importa durante a corrida. Se o Redis for esvaziado
no meio da corrida, a rota é lida de novo do banco e o rastro recomeça: a pior consequência é demorar
alguns minutos para o próximo aviso.
"""
from __future__ import annotations

import json
from typing import Protocol

import redis

from app.domain.geo import GeoPoint
from app.domain.safety import PositionSample

_TTL_S = 6 * 3600       # uma corrida não passa disso; depois o Redis limpa sozinho


class SafetyStore(Protocol):
    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        """Acrescenta a posição e devolve as últimas `max_samples`, da mais antiga à mais nova."""

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        """A rota esperada, `[]` se a corrida não tem rota guardada, ou None se ainda não foi carregada."""

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None: ...

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        """True se ninguém pegou `key` nos últimos `cooldown_s` segundos (e passa a valer como pegada agora)."""


class InMemorySafetyStore:
    def __init__(self) -> None:
        self._samples: dict[str, list[PositionSample]] = {}
        self._routes: dict[str, list[GeoPoint]] = {}
        self._claims: dict[str, float] = {}

    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        samples = self._samples.setdefault(ride_id, [])
        samples.append(sample)
        del samples[:-max_samples]
        return list(samples)

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        return self._routes.get(ride_id)

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None:
        self._routes[ride_id] = list(route)

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        until = self._claims.get(key)
        if until is not None and now < until:
            return False
        self._claims[key] = now + cooldown_s
        return True


# Pegar o aviso numa ida só ao Redis: com GET e SET separados, dois pedidos ao mesmo tempo avisariam duas vezes.
_CLAIM_LUA = """
local blocked_until = redis.call('get', KEYS[1])
if blocked_until and tonumber(ARGV[1]) < tonumber(blocked_until) then return 0 end
redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class RedisSafetyStore:
    def __init__(self, client: redis.Redis, prefix: str = "safety:") -> None:
        if not client.connection_pool.connection_kwargs.get("decode_responses"):
            raise ValueError("o cliente Redis precisa ser criado com decode_responses=True")
        self.r = client
        self.prefix = prefix
        self._claim = client.register_script(_CLAIM_LUA)

    def add_sample(self, ride_id: str, sample: PositionSample, max_samples: int) -> list[PositionSample]:
        key = f"{self.prefix}s:{ride_id}"
        pipe = self.r.pipeline()
        pipe.rpush(key, f"{sample.t!r},{sample.point.lat!r},{sample.point.lng!r}")
        pipe.ltrim(key, -max_samples, -1)
        pipe.expire(key, _TTL_S)
        pipe.lrange(key, 0, -1)
        raw = pipe.execute()[-1]
        samples = []
        for item in raw:
            t, lat, lng = item.split(",")
            samples.append(PositionSample(GeoPoint(float(lat), float(lng)), float(t)))
        return samples

    def get_route(self, ride_id: str) -> list[GeoPoint] | None:
        raw = self.r.get(f"{self.prefix}r:{ride_id}")
        if raw is None:
            return None
        return [GeoPoint(lat, lng) for lat, lng in json.loads(raw)]

    def set_route(self, ride_id: str, route: list[GeoPoint]) -> None:
        self.r.set(f"{self.prefix}r:{ride_id}", json.dumps([[p.lat, p.lng] for p in route]), ex=_TTL_S)

    def claim(self, key: str, now: float, cooldown_s: float) -> bool:
        return bool(
            self._claim(keys=[f"{self.prefix}c:{key}"], args=[repr(now), repr(now + cooldown_s), int(cooldown_s) + 60])
        )
````

Altere `server/app/runtime.py`:

````diff
--- a/server/app/runtime.py
+++ b/server/app/runtime.py
@@ -19,11 +19,13 @@ from sqlalchemy.exc import OperationalError
 from sqlalchemy.orm import Session
 
 from app.adapters.fake_maps import FakeMaps
+from app.adapters.fake_notifier import FakeContactNotifier
 from app.adapters.fake_otp import DevOtpSender
 from app.adapters.fake_payments import FakePaymentProvider
 from app.db.config_store import AppConfig, load_app_config
 from app.db.session import make_engine, make_session_factory
 from app.domain.maps import MapsProvider
+from app.domain.notifier import ContactNotifier
 from app.domain.payments import PaymentProvider
 from app.api.webhook import HmacVerifier, WebhookVerifier
 from app.infra.documents import DocumentStore, LocalDocumentStore
@@ -40,6 +42,7 @@ from app.infra.redis_store import (
     RedisRateLimiter,
     RedisReservationBook,
 )
+from app.infra.safety_store import RedisSafetyStore, SafetyStore
 from app.realtime.hub import Hub
 from app.services.auth import AuthService, OtpSender
 from app.services.dispatch import DispatchService, Reservations
@@ -48,6 +51,7 @@ from app.services.payments import PaymentService
 from app.services.quotes import QuoteService
 from app.services.ride_requests import RideRequestService
 from app.services.riders import RiderService
+from app.services.safety import SafetyService
 from app.services.sweeps import SweepService
 from app.services.trips import TripService
 from app.settings import Settings
@@ -76,6 +80,7 @@ class Unit:
     quotes: QuoteService
     requests: RideRequestService
     sweeps: SweepService
+    safety: SafetyService
 
 
 @dataclass
@@ -93,6 +98,8 @@ class Runtime:
     job_marks: JobMarks
     documents: DocumentStore
     webhook_verifier: WebhookVerifier
+    safety_store: SafetyStore
+    notifier: ContactNotifier
     mode: str = "production"
     clock: Callable[[], float] = time.time
     redis_client: Any = None
@@ -129,6 +136,7 @@ class Runtime:
             quotes=QuoteService(self.maps, self.positions, self.factors, cfg),
             requests=RideRequestService(dispatch, events, cfg),
             sweeps=SweepService(payments, dispatch, trips, events, cfg),
+            safety=SafetyService(self.safety_store, self.positions, self.notifier, events, cfg),
         )
 
     def run(self, work: Callable[[Unit], T], *, retries: int = 2) -> T:
@@ -192,6 +200,8 @@ def build_runtime(settings: Settings) -> Runtime:
         job_marks=RedisJobMarks(client),
         documents=LocalDocumentStore(settings.upload_dir),
         webhook_verifier=HmacVerifier(settings.webhook_secret),
+        safety_store=RedisSafetyStore(client),
+        notifier=FakeContactNotifier(),
         mode="dev",
         redis_client=client,
     )
````

Crie `server/app/services/safety.py`:

````python
"""Segurança durante a corrida: parada longa, saída da rota, localização falsa e SOS (spec, seção 9).

O aviso automático pergunta ao passageiro se está tudo bem; o SOS fica disponível durante toda a corrida.
Os dois avisam os administradores. O telefonema para o 190 é feito pelo próprio app do passageiro.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import queries
from app.db import repositories as repo
from app.db.config_store import AppConfig
from app.db.models import SafetyAlertRow, UserRow
from app.domain.geo import GeoPoint
from app.domain.notifier import ContactNotifier
from app.domain.rides import InvalidTransition, RideState
from app.domain.safety import PositionSample, evaluate
from app.infra.redis_store import PositionStore
from app.infra.safety_store import SafetyStore
from app.services.events import EventCollector
from app.services.trips import NotYourRide

log = logging.getLogger("app.safety")

SOS_REPEAT_S = 300.0        # SOS apertado de novo dentro desse tempo não avisa o contato outra vez
_MOCK_ONCE_S = 3600.0
_ON_THE_MOVE = (RideState.ACCEPTED, RideState.ARRIVED, RideState.IN_PROGRESS)


class AlertClosed(Exception):
    """O alerta já foi respondido ou encerrado."""


@dataclass(frozen=True)
class SosResult:
    alert_id: int
    contact_registered: bool
    contact_notified: bool
    repeated: bool


class SafetyService:
    def __init__(
        self,
        store: SafetyStore,
        positions: PositionStore,
        notifier: ContactNotifier,
        events: EventCollector,
        cfg: AppConfig | None = None,
    ) -> None:
        self.store = store
        self.positions = positions
        self.notifier = notifier
        self.events = events
        self.cfg = cfg or AppConfig.defaults()

    # --- aviso automático ----------------------------------------------------------------------

    def _route(self, session: Session, ride_id: str) -> list[GeoPoint]:
        route = self.store.get_route(ride_id)
        if route is None:           # primeira posição da corrida (ou o Redis foi esvaziado): lê do banco uma vez
            try:
                route = [GeoPoint(lat, lng) for lat, lng in repo.get_ride_details(session, ride_id).route]
            except LookupError:
                route = []
            self.store.set_route(ride_id, route)
        return route

    def _notify_admins(self, session: Session, type: str, payload: dict) -> None:
        for admin_id in queries.admin_ids(session):
            self.events.add(admin_id, type, payload)

    def on_rider_position(
        self, session: Session, ride_id: str, passenger_id: str, point: GeoPoint, now: float
    ) -> SafetyAlertRow | None:
        """Chamado a cada posição do motoqueiro numa corrida em andamento. Devolve o alerta criado, se houve."""
        cfg = self.cfg.safety
        samples = self.store.add_sample(ride_id, PositionSample(point, now), cfg.max_samples)
        result = evaluate(samples, self._route(session, ride_id), cfg)
        if result.suspected_mock_location and self.store.claim(f"{ride_id}:mock", now, _MOCK_ONCE_S):
            repo.log_ride_event(session, ride_id, "mock_location_suspected", {}, now)
            self._notify_admins(session, "mock_location_suspected", {"ride_id": ride_id})
        if result.alert is None or not self.store.claim(f"{ride_id}:{result.alert.value}", now, cfg.alert_cooldown_s):
            return None
        alert = SafetyAlertRow(
            ride_id=ride_id, kind=result.alert.value, status="open", suspected_mock=result.suspected_mock_location,
            lat=point.lat, lng=point.lng, created_at=now,
        )
        session.add(alert)
        session.flush()
        self.events.add(passenger_id, "safety_check", {"ride_id": ride_id, "alert_id": alert.id, "kind": alert.kind})
        self._notify_admins(
            session, "safety_alert",
            {"alert_id": alert.id, "ride_id": ride_id, "kind": alert.kind, "lat": point.lat, "lng": point.lng},
        )
        return alert

    def answer_ok(self, session: Session, passenger_id: str, ride_id: str, alert_id: int, now: float) -> None:
        alert = session.get(SafetyAlertRow, alert_id, with_for_update=True)
        if alert is None or alert.ride_id != ride_id:
            raise LookupError(f"alerta {alert_id} não encontrado")
        if repo.get_ride(session, ride_id).passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        if alert.status != "open":
            raise AlertClosed("Esse aviso já foi respondido.")
        alert.status, alert.answered_at = "ok", now
        session.flush()
        self._notify_admins(session, "safety_ok", {"alert_id": alert_id, "ride_id": ride_id})

    # --- SOS ---------------------------------------------------------------------------------------

    def sos(self, session: Session, passenger_id: str, ride_id: str, now: float) -> SosResult:
        ride = repo.get_ride(session, ride_id)
        if ride.passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        if ride.state not in _ON_THE_MOVE:
            raise InvalidTransition("O SOS vale só durante a corrida.")
        contact = repo.get_emergency_contact(session, passenger_id)
        if not self.store.claim(f"{ride_id}:sos", now, SOS_REPEAT_S):
            previous = session.query(SafetyAlertRow).filter_by(ride_id=ride_id, kind="sos").order_by(
                SafetyAlertRow.id.desc()
            ).first()
            if previous is not None:
                return SosResult(previous.id, contact is not None, previous.note == "contato avisado", True)
        where = self.positions.get(ride.rider_id) if ride.rider_id else None
        alert = SafetyAlertRow(
            ride_id=ride_id, kind="sos", status="sos", lat=where.lat if where else None,
            lng=where.lng if where else None, created_at=now,
        )
        session.add(alert)
        session.execute(
            update(SafetyAlertRow).where(SafetyAlertRow.ride_id == ride_id, SafetyAlertRow.status == "open")
            .values(status="sos")
        )
        notified = False
        if contact is None:
            alert.note = "sem contato cadastrado"
        else:
            try:
                self.notifier.notify(contact.phone, self._sos_text(session, ride_id, passenger_id, where))
                notified, alert.note = True, "contato avisado"
            except Exception:       # o WhatsApp fora do ar não pode impedir o SOS
                log.exception("falha ao avisar o contato de emergência da corrida %s", ride_id)
                alert.note = "falha ao avisar o contato"
        session.flush()
        self.events.add(
            passenger_id, "sos_sent",
            {"alert_id": alert.id, "contact_registered": contact is not None, "contact_notified": notified},
        )
        self._notify_admins(
            session, "sos",
            {
                "alert_id": alert.id, "ride_id": ride_id, "passenger_id": passenger_id, "rider_id": ride.rider_id,
                "lat": alert.lat, "lng": alert.lng, "contact_notified": notified,
            },
        )
        return SosResult(alert.id, contact is not None, notified, False)

    @staticmethod
    def _sos_text(session: Session, ride_id: str, passenger_id: str, where: GeoPoint | None) -> str:
        ride = repo.get_ride(session, ride_id)
        passenger = session.get(UserRow, passenger_id)
        card = queries.rider_card(session, ride.rider_id)
        place = (
            f"Última posição: https://maps.google.com/?q={where.lat:.6f},{where.lng:.6f}"
            if where else "A posição da moto não está disponível."
        )
        return (
            f"{passenger.name} pediu socorro durante uma corrida de moto. "
            f"Moto {card.moto_model}, placa {card.plate}, motoqueiro {card.name}. {place}"
        )

    # --- administrador ---------------------------------------------------------------------------------

    def resolve(self, session: Session, alert_id: int, admin_id: str, note: str, now: float) -> None:
        alert = session.get(SafetyAlertRow, alert_id, with_for_update=True)
        if alert is None:
            raise LookupError(f"alerta {alert_id} não encontrado")
        if alert.status == "resolved":
            raise AlertClosed("Esse alerta já foi encerrado.")
        alert.status, alert.resolved_at, alert.resolved_by = "resolved", now, admin_id
        alert.note = note[:200] or alert.note
        session.flush()
````

Crie `server/migrations/versions/0004_alertas_de_seguranca.py`:

````python
"""alertas de segurança da corrida (parada longa, saída da rota, SOS)

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ride_id", sa.String(40), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("suspected_mock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lat", sa.Float(53), nullable=True),
        sa.Column("lng", sa.Float(53), nullable=True),
        sa.Column("created_at", sa.Float(53), nullable=False),
        sa.Column("answered_at", sa.Float(53), nullable=True),
        sa.Column("resolved_at", sa.Float(53), nullable=True),
        sa.Column("resolved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.CheckConstraint("kind IN ('stopped','off_route','sos')", name="alert_kind_valid"),
        sa.CheckConstraint("status IN ('open','ok','sos','resolved')", name="alert_status_valid"),
    )
    op.create_index("ix_safety_alerts_status", "safety_alerts", ["status"])
    op.create_index("ix_safety_alerts_ride_id", "safety_alerts", ["ride_id"])


def downgrade() -> None:
    op.drop_table("safety_alerts")
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q \
  tests/api/test_safety_routes.py \
  tests/db/test_migracoes_reversiveis.py \
  tests/db/test_schema_safety.py \
  tests/domain/test_safety_api.py \
  tests/infra/test_safety_store.py \
  tests/services/test_safety.py`
Expected: `35 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `651 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Aplicar a migração no banco de desenvolvimento e conferir**

Run: `.venv/bin/alembic upgrade head`
Expected: termina com `Running upgrade 0003 -> 0004`

Run: `.venv/bin/alembic current`
Expected: `0004 (head)`

- [ ] **Step 7: Commit**

```bash
cd .. && git add server && git commit -m "feat(safety): alertas de parada e saída da rota, SOS e migração 0004" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 11: Tempo real e tarefas repetidas: WebSocket, varredura, tarefa diária e limpeza

O WebSocket (`/v1/ws`) entrega os avisos; o agendador roda dentro do servidor: varredura de tempo a cada 3 s (cada corrida é gravada e publicada na hora), checagem diária de documentos vencidos e limpeza das posições. `SweepService.run` ganha o gancho de publicação.

**Files:**
- Modify: `server/app/api/app.py`
- Create: `server/app/api/routes/ws.py`
- Create: `server/app/scheduler.py`
- Modify: `server/app/services/sweeps.py`
- Test: `server/tests/api/test_scheduler.py` (novo)
- Test: `server/tests/api/test_ws.py` (novo)
- Test: `server/tests/services/test_sweeps.py` (alterado)

**Interfaces:**
- Consumes: `Runtime`, `SweepService`, `RiderService.block_expired_documents`, `PositionStore.prune`, `JobMarks`, `Hub`.
- Produces: `SweepService.run(session, now, after_commit=None)`; `app.scheduler`: `sweep_once(runtime) -> SweepReport`, `run_daily_jobs(runtime) -> int | None`, `prune_positions(runtime) -> int`, `POSITION_MAX_AGE_S`, `Scheduler(runtime, *, sweep_interval_s=3.0, maintenance_every_s=60.0)` com `tick()` e `async run()`; `app.api.routes.ws`: `AUTH_TIMEOUT_S`, `CLOSE_UNAUTHORIZED = 4401`, `CLOSE_RESYNC = 4408`, `pump(websocket, connection)`; `create_app(runtime, *, run_background=False, scheduler=None)`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/api/test_scheduler.py`:

````python
import asyncio
import datetime as dt
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.db.models import RiderProfileRow
from app.domain.clock import local_date
from app.scheduler import POSITION_MAX_AGE_S, Scheduler, prune_positions, run_daily_jobs, sweep_once
from app.services.payments import PaymentService
from app.services.riders import RiderService
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


def pix_aceito(client, runtime, session, clock):
    pax = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    online_rider(session, runtime, clock, 1)
    rider = login(client, runtime, rider_phone(1), "rider")
    quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
    pedido = client.post(
        "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "pix"}, headers=pax.headers
    ).json()
    client.post(f"/v1/rider/offers/{pedido['ride_id']}/accept", headers=rider.headers)
    return pax, rider, pedido


# --- varredura ------------------------------------------------------------------------------------


def test_varredura_cancela_pix_vencido_e_publica_os_avisos_depois_do_commit(client, runtime, session, clock, listen):
    pax, rider, pedido = pix_aceito(client, runtime, session, clock)
    avisos_pax, avisos_rider = listen(pax.user_id), listen(rider.user_id)
    assert sweep_once(runtime).pix_expired == 0
    clock.advance(121)
    relatorio = sweep_once(runtime)
    assert relatorio.pix_expired == 1 and relatorio.errors == []
    assert avisos_pax.types == ["ride_cancelled"] and avisos_rider.types == ["ride_cancelled"]
    assert avisos_pax.messages[0]["data"] == {"ride_id": pedido["ride_id"], "reason": "pix_expired"}
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None


def test_erro_numa_corrida_vai_para_o_registro_e_o_servidor_segue(
    client, runtime, session, clock, monkeypatch, caplog
):
    pix_aceito(client, runtime, session, clock)
    clock.advance(121)

    def quebra(self, *args, **kwargs):
        raise RuntimeError("provedor caiu")

    monkeypatch.setattr(PaymentService, "expire_unpaid_pix", quebra)
    with caplog.at_level(logging.ERROR, logger="app.scheduler"):
        relatorio = sweep_once(runtime)
    assert len(relatorio.errors) == 1 and relatorio.pix_expired == 0
    assert any("provedor caiu" in r.getMessage() for r in caplog.records)


# --- tarefa diária de documentos --------------------------------------------------------------------


def rider_com_cnh_vencida(session, runtime, clock):
    rider_id = online_rider(session, runtime, clock, 1)
    session.get(RiderProfileRow, rider_id).cnh_expires_on = local_date(clock.now) - dt.timedelta(days=1)
    session.commit()        # a unidade que falha desfaz o que não foi gravado; o cenário precisa estar gravado
    return rider_id


def test_documento_vencido_bloqueia_uma_vez_por_dia(runtime, session, clock, listen):
    rider_id = rider_com_cnh_vencida(session, runtime, clock)
    avisos = listen(rider_id)
    assert run_daily_jobs(runtime) == 1
    perfil = session.get(RiderProfileRow, rider_id)
    assert (perfil.status, perfil.online, perfil.rejected_reason) == ("blocked", False, "documento vencido")
    assert avisos.types == ["documents_expired"] and runtime.positions.get(rider_id) is None
    assert run_daily_jobs(runtime) is None                       # já rodou hoje
    clock.advance(86_400)
    assert run_daily_jobs(runtime) == 0                          # outro dia, nada novo para bloquear


def test_se_a_tarefa_diaria_falhar_ela_tenta_de_novo_na_proxima_volta(runtime, session, clock, monkeypatch):
    rider_id = rider_com_cnh_vencida(session, runtime, clock)
    original = RiderService.block_expired_documents
    chamadas = []

    def falha_na_primeira(self, *args, **kwargs):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("banco caiu")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RiderService, "block_expired_documents", falha_na_primeira)
    with pytest.raises(RuntimeError):
        run_daily_jobs(runtime)
    assert run_daily_jobs(runtime) == 1
    assert session.get(RiderProfileRow, rider_id).status == "blocked"


# --- limpeza das posições ---------------------------------------------------------------------------


def test_limpeza_tira_do_mapa_quem_some_sem_avisar(runtime, clock):
    runtime.positions.update("sumiu", pt(0, 0), clock.now - POSITION_MAX_AGE_S - 1)
    runtime.positions.update("firme", pt(10, 0), clock.now - 30)
    assert prune_positions(runtime) == 1
    assert runtime.positions.get("sumiu") is None and runtime.positions.get("firme") is not None


# --- o agendador ----------------------------------------------------------------------------------------


def test_cada_volta_varre_e_a_manutencao_so_roda_de_minuto_em_minuto(runtime, clock, monkeypatch):
    chamadas = []
    monkeypatch.setattr("app.scheduler.sweep_once", lambda rt: chamadas.append("varre"))
    monkeypatch.setattr("app.scheduler.run_daily_jobs", lambda rt: chamadas.append("diaria"))
    monkeypatch.setattr("app.scheduler.prune_positions", lambda rt: chamadas.append("limpa"))
    agendador = Scheduler(runtime)
    agendador.tick()
    clock.advance(3)
    agendador.tick()
    clock.advance(58)
    agendador.tick()
    assert chamadas == ["varre", "diaria", "limpa", "varre", "varre", "diaria", "limpa"]


def test_uma_volta_que_estoura_nao_derruba_o_agendador(runtime, caplog):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)
            if len(voltas) == 1:
                raise RuntimeError("banco caiu")

    async def main():
        tarefa = asyncio.create_task(Agendador(runtime, sweep_interval_s=0.01).run())
        while len(voltas) < 3:
            await asyncio.sleep(0.01)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa

    with caplog.at_level(logging.ERROR, logger="app.scheduler"):
        asyncio.run(main())
    assert len(voltas) >= 3 and any("banco caiu" in r.getMessage() for r in caplog.records)


def test_o_agendador_liga_com_o_servidor_e_para_junto(runtime):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)

    with TestClient(create_app(runtime, run_background=True, scheduler=Agendador(runtime, sweep_interval_s=0.01))):
        for _ in range(200):
            if len(voltas) >= 3:
                break
            time.sleep(0.01)
        assert len(voltas) >= 3
    parou_em = len(voltas)
    time.sleep(0.1)
    assert len(voltas) == parou_em


def test_sem_run_background_nao_tem_agendador(runtime):
    voltas = []

    class Agendador(Scheduler):
        def tick(self):
            voltas.append(1)

    with TestClient(create_app(runtime, scheduler=Agendador(runtime, sweep_interval_s=0.01))):
        time.sleep(0.1)
    assert voltas == []
````

Crie `server/tests/api/test_ws.py`:

````python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routes import ws as ws_module
from app.db.models import UserRow
from app.realtime.hub import Connection
from tests.api.helpers import login, online_rider, rider_phone
from tests.helpers import ORIGIN, pt

_pool = ThreadPoolExecutor(max_workers=4)


def receber(ws, segundos=3.0):
    """`receive_json` sem ficar preso para sempre se o aviso não vier."""
    return _pool.submit(ws.receive_json).result(timeout=segundos)


@contextmanager
def conectado(client, quem):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": quem.token})
        assert receber(ws)["type"] == "ready"
        yield ws


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


@pytest.fixture()
def pax(client, runtime):
    return login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")


@pytest.fixture()
def rider(client, runtime, session, clock):
    online_rider(session, runtime, clock, 1)
    return login(client, runtime, rider_phone(1), "rider")


def test_conexao_autorizada_recebe_o_pronto_com_quem_e(client, pax, runtime):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": pax.token})
        pronto = receber(ws)
    assert pronto == {"type": "ready", "data": {"user_id": pax.user_id, "role": "passenger"}, "at": runtime.clock()}


def test_os_avisos_chegam_so_a_quem_e_deles_depois_do_commit(client, pax, rider):
    with conectado(client, pax) as ws_pax, conectado(client, rider) as ws_rider:
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
        pedido = client.post(
            "/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers
        ).json()
        oferta = receber(ws_rider)
        assert oferta["type"] == "offer" and oferta["data"]["ride_id"] == pedido["ride_id"]
        client.post(f"/v1/rider/offers/{pedido['ride_id']}/accept", headers=rider.headers)
        aceito = receber(ws_pax)
        assert aceito["type"] == "rider_accepted" and aceito["data"]["pin"] == pedido["pin"]
        assert receber(ws_rider)["type"] == "ride_assigned"


def test_duas_telas_do_mesmo_usuario_recebem_o_mesmo_aviso(client, pax, rider, runtime):
    with conectado(client, rider) as primeira, conectado(client, rider) as segunda:
        assert runtime.hub.count() == 2
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).json()
        client.post("/v1/passenger/rides", json={"quote_id": quote["quote_id"], "method": "cash"}, headers=pax.headers)
        assert receber(primeira)["type"] == "offer" and receber(segunda)["type"] == "offer"


def test_sair_tira_a_conexao_do_hub(client, pax, runtime):
    with conectado(client, pax):
        assert runtime.hub.count() == 1
    assert runtime.hub.count() == 0


@pytest.mark.parametrize("primeira", [{"token": "inventado"}, {"token": 123}, {"oi": 1}, [], "texto"])
def test_primeira_mensagem_ruim_fecha_com_4401(client, primeira):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json(primeira)
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_primeira_mensagem_que_nao_e_json_fecha_com_4401(client):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_text("isto não é json")
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_quem_nao_se_identifica_a_tempo_e_desconectado(client, monkeypatch):
    monkeypatch.setattr(ws_module, "AUTH_TIMEOUT_S", 0.2)
    with client.websocket_connect("/v1/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as erro:
            receber(ws)
    assert erro.value.code == 4401


def test_conta_bloqueada_ou_sessao_encerrada_nao_conecta(client, pax, rider, session):
    client.post("/v1/auth/logout", headers=pax.headers)
    session.get(UserRow, rider.user_id).is_blocked = True
    session.flush()
    for quem in (pax, rider):
        with client.websocket_connect("/v1/ws") as ws:
            ws.send_json({"token": quem.token})
            with pytest.raises(WebSocketDisconnect) as erro:
                receber(ws)
        assert erro.value.code == 4401


def test_o_cliente_pode_mandar_ping_de_texto_sem_derrubar_a_conexao(client, pax):
    with conectado(client, pax) as ws:
        ws.send_text("ping")
        ws.send_bytes(b"\x00")
        ws.send_text("ping")
        resposta = client.get("/v1/me", headers=pax.headers)
        assert resposta.status_code == 200


# --- a bomba que entrega a fila à tela, testada sem rede ------------------------------------------


class TelaFalsa:
    def __init__(self, depois_de=None):
        self.enviados, self.fechou_com = [], None
        self.saiu = asyncio.Event()

    async def receive(self):
        await self.saiu.wait()
        return {"type": "websocket.disconnect"}

    async def send_json(self, message):
        self.enviados.append(message)

    async def close(self, code=1000):
        self.fechou_com = code


def test_bomba_entrega_na_ordem_e_termina_quando_a_tela_sai():
    async def main():
        tela, conexao = TelaFalsa(), Connection("u1", asyncio.get_running_loop())
        tarefa = asyncio.create_task(ws_module.pump(tela, conexao))
        conexao.deliver({"i": 1})
        conexao.deliver({"i": 2})
        for _ in range(20):
            await asyncio.sleep(0.01)
        tela.saiu.set()
        await asyncio.wait_for(tarefa, 1)
        return tela.enviados, tela.fechou_com

    assert asyncio.run(main()) == ([{"i": 1}, {"i": 2}], None)


def test_bomba_fecha_a_conexao_com_fila_cheia_para_o_app_pedir_o_estado_de_novo():
    async def main():
        tela, conexao = TelaFalsa(), Connection("u1", asyncio.get_running_loop(), max_queue=1)
        conexao.deliver({"i": 1})
        conexao.deliver({"i": 2})
        await asyncio.sleep(0.01)
        await asyncio.wait_for(ws_module.pump(tela, conexao), 1)
        return tela.enviados, tela.fechou_com

    assert asyncio.run(main()) == ([], 4408)
````

Altere `server/tests/services/test_sweeps.py`:

````diff
--- a/server/tests/services/test_sweeps.py
+++ b/server/tests/services/test_sweeps.py
@@ -228,3 +228,49 @@ def test_qr_que_faltou_e_criado_depois_e_o_passageiro_ganha_um_prazo_novo(sessio
     assert sweeps.run(session, fim + 310 + 299).cash_blocked == 0       # o prazo de 5 minutos recomeça no QR
     assert sweeps.run(session, fim + 310 + 300).cash_blocked == 1
 
+
+
+def _dois_pix_vencidos(w, session, positions, events):
+    add_passenger(session)
+    add_passenger(session, "p2", "+5575900002002")
+    aceitar(session, positions, w, ride_id="ride-1", passenger_id="p1", rider_n=1)
+    aceitar(session, positions, w, ride_id="ride-2", passenger_id="p2", rider_n=2)
+    events.drain()          # os avisos do pedido e do aceite já foram publicados
+
+
+def test_com_publicacao_cada_corrida_e_gravada_e_publicada_na_hora(w, session, positions, events, monkeypatch):
+    # Roteiro do 2B: "um commit por corrida, para segurar as travas por menos tempo".
+    _dois_pix_vencidos(w, session, positions, events)
+    passos: list = []
+    commit_de_verdade = session.commit
+
+    def commit_anotado():
+        passos.append("commit")
+        commit_de_verdade()
+
+    monkeypatch.setattr(session, "commit", commit_anotado)
+
+    def depois():
+        passos.append([e.type for e in events.drain()])
+
+    relatorio = w.sweeps.run(session, AGORA + 1 + 120, after_commit=depois)
+    assert relatorio.pix_expired == 2 and relatorio.errors == []
+    assert passos == ["commit", ["ride_cancelled", "ride_cancelled"]] * 2
+
+
+def test_corrida_com_erro_nao_impede_as_outras_e_seus_avisos_nao_saem(w, session, positions, events, monkeypatch):
+    _dois_pix_vencidos(w, session, positions, events)
+    original = w.payments.expire_unpaid_pix
+
+    def quebra_na_primeira(sessao, ride_id, now):
+        if ride_id == "ride-1":
+            raise RuntimeError("provedor caiu")
+        return original(sessao, ride_id, now)
+
+    monkeypatch.setattr(w.payments, "expire_unpaid_pix", quebra_na_primeira)
+    publicados: list = []
+    relatorio = w.sweeps.run(session, AGORA + 1 + 120, after_commit=lambda: publicados.extend(events.drain()))
+    assert relatorio.pix_expired == 1 and len(relatorio.errors) == 1 and "ride-1" in relatorio.errors[0]
+    assert repo.get_ride(session, "ride-1").state is RideState.ACCEPTED
+    assert repo.get_ride(session, "ride-2").state is RideState.CANCELLED
+    assert {e.user_id for e in publicados} == {"p2", "r2"}
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_scheduler.py tests/api/test_ws.py tests/services/test_sweeps.py`
Expected: erro ao carregar os testes — `ModuleNotFoundError: No module named 'app.scheduler'`.

- [ ] **Step 3: Implementar**

Altere `server/app/api/app.py`:

````diff
--- a/server/app/api/app.py
+++ b/server/app/api/app.py
@@ -1,6 +1,9 @@
 """Montagem da aplicação FastAPI. As rotas ficam em `app/api/routes/`; a lógica, nos serviços."""
 from __future__ import annotations
 
+import asyncio
+import contextlib
+
 from fastapi import FastAPI
 from fastapi.responses import JSONResponse
 
@@ -13,17 +16,33 @@ from app.api.routes import payments as payments_routes
 from app.api.routes import rider as rider_routes
 from app.api.routes import rides as rides_routes
 from app.api.routes import safety as safety_routes
+from app.api.routes import ws as ws_routes
+from app.scheduler import Scheduler
 
 
-def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
+def create_app(runtime=None, *, run_background: bool = False, scheduler: Scheduler | None = None) -> FastAPI:
     """`runtime` reúne banco, Redis e adaptadores (ver `app/runtime.py`). `run_background` liga o
     agendador (varreduras de tempo); os testes deixam desligado e chamam as tarefas à mão."""
     dev = getattr(runtime, "mode", "production") == "dev"
+
+    @contextlib.asynccontextmanager
+    async def lifespan(app: FastAPI):
+        task = None
+        if run_background and runtime is not None:
+            task = asyncio.create_task((scheduler or Scheduler(runtime)).run())
+        try:
+            yield
+        finally:
+            if task is not None:
+                task.cancel()
+                await asyncio.gather(task, return_exceptions=True)
+
     app = FastAPI(
         title="App de corrida do Recôncavo",
         docs_url="/docs" if dev else None,
         redoc_url=None,
         openapi_url="/openapi.json" if dev else None,
+        lifespan=lifespan,
     )
     app.state.runtime = runtime
     install_error_handlers(app)
@@ -35,8 +54,9 @@ def create_app(runtime=None, *, run_background: bool = False) -> FastAPI:
     app.include_router(rides_routes.router)
     app.include_router(payments_routes.router)
     app.include_router(safety_routes.router)
+    app.include_router(ws_routes.router)
 
-    if getattr(runtime, "mode", None) == "dev":
+    if dev:
         from app.api.routes import dev as dev_routes
 
         app.include_router(dev_routes.router)
````

Crie `server/app/api/routes/ws.py`:

````python
"""Avisos em tempo real por WebSocket.

O app abre a conexão, manda `{"token": "..."}` como primeira mensagem (o token não vai na URL, que fica
nos registros) e passa a receber `{"type", "data", "at"}`. Os avisos são dicas: ao reconectar, o app
pede o estado de novo (`/v1/passenger/state` ou `/v1/rider/state`), que é a fonte da verdade.
"""
from __future__ import annotations

import asyncio

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.realtime.hub import Connection

router = APIRouter(tags=["tempo real"])

AUTH_TIMEOUT_S = 10.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_RESYNC = 4408         # a fila encheu: reconecte e peça o estado


async def pump(websocket, connection: Connection) -> None:
    """Entrega à tela o que chega na fila. Termina quando a tela sai, a fila encheu ou o envio falha."""
    async with anyio.create_task_group() as group:

        async def reader() -> None:
            while True:                    # o app manda "ping" de vez em quando; o conteúdo não importa
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    group.cancel_scope.cancel()
                    return

        group.start_soon(reader)
        try:
            while True:
                if connection.overflowed:
                    await websocket.close(code=CLOSE_RESYNC)
                    break
                message = await connection.queue.get()
                if connection.overflowed:
                    await websocket.close(code=CLOSE_RESYNC)
                    break
                await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):     # a tela saiu no meio do envio
            pass
        group.cancel_scope.cancel()


@router.websocket("/v1/ws")
async def events_socket(websocket: WebSocket) -> None:
    runtime = websocket.app.state.runtime
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_S)
        token = first["token"] if isinstance(first, dict) else None
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError):
        token = None
    user = None
    if isinstance(token, str) and token:
        user = await run_in_threadpool(
            runtime.run, lambda unit: unit.auth.authenticate(unit.session, token, unit.now)
        )
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    connection = Connection(user.user_id, asyncio.get_running_loop())
    runtime.hub.add(connection)
    try:
        await websocket.send_json(
            {"type": "ready", "data": {"user_id": user.user_id, "role": user.role}, "at": runtime.clock()}
        )
        await pump(websocket, connection)
    finally:
        runtime.hub.remove(connection)
````

Crie `server/app/scheduler.py`:

````python
"""Tarefas que o servidor repete sozinho: varredura de tempo, checagem diária de documentos e limpeza."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.domain.clock import local_date
from app.runtime import Runtime
from app.services.sweeps import SweepReport

log = logging.getLogger("app.scheduler")

POSITION_MAX_AGE_S = 600.0          # motoqueiro sem mandar posição há 10 minutos sai do mapa
DAILY_DOCS_MARK = "docs"


def sweep_once(runtime: Runtime) -> SweepReport:
    """Uma rodada de varredura: cada corrida é gravada e publicada na hora, as que falham vão para o registro."""
    with runtime.session_factory() as session:
        unit = runtime.make_unit(session)

        def publish() -> None:
            runtime.publish(unit.events.drain(), unit.now)

        report = unit.sweeps.run(session, unit.now, after_commit=publish)
        session.commit()
        publish()
    for error in report.errors:
        log.error("varredura: %s", error)
    return report


def run_daily_jobs(runtime: Runtime) -> int | None:
    """Bloqueia quem está com CNH ou documento da moto vencido, uma vez por dia (dia da Bahia).

    Devolve quantos foram bloqueados, ou None se hoje já rodou. Se falhar, não marca o dia: tenta de novo.
    """
    today = local_date(runtime.clock())
    if runtime.job_marks.get(DAILY_DOCS_MARK) == today.isoformat():
        return None
    blocked = runtime.run(lambda unit: unit.riders.block_expired_documents(unit.session, local_date(unit.now)))
    runtime.job_marks.set(DAILY_DOCS_MARK, today.isoformat())
    return len(blocked)


def prune_positions(runtime: Runtime) -> int:
    return runtime.positions.prune(runtime.clock(), POSITION_MAX_AGE_S)


class Scheduler:
    def __init__(self, runtime: Runtime, *, sweep_interval_s: float = 3.0, maintenance_every_s: float = 60.0) -> None:
        self.runtime = runtime
        self.sweep_interval_s = sweep_interval_s
        self.maintenance_every_s = maintenance_every_s
        self._last_maintenance: float | None = None

    @staticmethod
    def _safely(label: str, step: Callable[[], object]) -> None:
        try:
            step()
        except Exception as exc:       # uma tarefa que falha não pode impedir as outras nem derrubar o servidor
            log.error("%s falhou: %s", label, exc, exc_info=True)

    def tick(self) -> None:
        """Uma volta: varre sempre; a cada `maintenance_every_s` faz também a tarefa diária e a limpeza."""
        self._safely("varredura", lambda: sweep_once(self.runtime))
        now = self.runtime.clock()
        if self._last_maintenance is None or now - self._last_maintenance >= self.maintenance_every_s:
            self._last_maintenance = now
            self._safely("tarefa diária", lambda: run_daily_jobs(self.runtime))
            self._safely("limpeza de posições", lambda: prune_positions(self.runtime))

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("volta do agendador falhou: %s", exc, exc_info=True)
            await asyncio.sleep(self.sweep_interval_s)
````

Altere `server/app/services/sweeps.py`:

````diff
--- a/server/app/services/sweeps.py
+++ b/server/app/services/sweeps.py
@@ -2,7 +2,10 @@
 
 Cada corrida é tratada num ponto de salvamento: se uma falhar, o banco volta ao que era, os avisos
 anotados naquela corrida são descartados, o erro vai para o relatório e as outras seguem. Os serviços
-e este precisam compartilhar o mesmo `EventCollector`. Quem chama faz o commit (ou o rollback) do conjunto.
+e este precisam compartilhar o mesmo `EventCollector`.
+
+Sem `after_commit`, quem chama faz o commit (ou o rollback) do conjunto. Com `after_commit`, cada corrida
+tratada sem erro é gravada na hora (para soltar as travas dela) e `after_commit()` publica os avisos dela.
 """
 from __future__ import annotations
 
@@ -49,7 +52,13 @@ class SweepService:
         self.cfg = cfg or AppConfig.defaults()
 
     def _each(
-        self, session: Session, report: SweepReport, label: str, ride_ids: list[str], action: Callable[[str], bool]
+        self,
+        session: Session,
+        report: SweepReport,
+        label: str,
+        ride_ids: list[str],
+        action: Callable[[str], bool],
+        after_commit: Callable[[], None] | None,
     ) -> int:
         done = 0
         for ride_id in ride_ids:
@@ -61,9 +70,13 @@ class SweepService:
             except Exception as exc:  # um pedido com problema não pode travar os outros
                 self.events.rollback_to(mark)   # os avisos desta corrida somem junto com o banco
                 report.errors.append(f"{label} {ride_id}: {exc}")
+                continue
+            if after_commit is not None:
+                session.commit()
+                after_commit()
         return done
 
-    def run(self, session: Session, now: float) -> SweepReport:
+    def run(self, session: Session, now: float, after_commit: Callable[[], None] | None = None) -> SweepReport:
         report = SweepReport()
         rides = self.cfg.rides
 
@@ -133,23 +146,26 @@ class SweepService:
                 return False
             return self.dispatcher.give_up_if_expired(session, ride_id, now)
 
-        report.offers_expired = self._each(session, report, "oferta", queries.due_offer_ride_ids(session, now), offers)
+        report.offers_expired = self._each(session, report, "oferta", queries.due_offer_ride_ids(session, now), offers, after_commit)
         report.pix_expired = self._each(
-            session, report, "pix", queries.pix_window_due_ride_ids(session, now, rides.pix_window_s), pix
+            session, report, "pix", queries.pix_window_due_ride_ids(session, now, rides.pix_window_s), pix, after_commit
         )
         report.queue_released = self._each(
-            session, report, "fila", queries.queued_ride_ids_due(session, now, rides.queue_max_wait_s), queue
+            session, report, "fila", queries.queued_ride_ids_due(session, now, rides.queue_max_wait_s), queue,
+            after_commit,
         )
         report.arrival_cancelled = self._each(
-            session, report, "chegada", queries.arrived_ride_ids_due(session, now, rides.max_wait_at_arrival_s), arrival
+            session, report, "chegada", queries.arrived_ride_ids_due(session, now, rides.max_wait_at_arrival_s), arrival,
+            after_commit,
         )
         report.qr_created = self._each(
-            session, report, "qr", queries.cash_rides_without_charge_ids(session), qr
+            session, report, "qr", queries.cash_rides_without_charge_ids(session), qr, after_commit
         )
         report.cash_blocked = self._each(
-            session, report, "dinheiro", queries.cash_unpaid_ride_ids_due(session, now, rides.cash_pay_wait_s), cash
+            session, report, "dinheiro", queries.cash_unpaid_ride_ids_due(session, now, rides.cash_pay_wait_s), cash,
+            after_commit,
         )
         report.searches_given_up = self._each(
-            session, report, "procura", queries.searching_ride_ids(session), searching
+            session, report, "procura", queries.searching_ride_ids(session), searching, after_commit
         )
         return report
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_scheduler.py tests/api/test_ws.py tests/services/test_sweeps.py`
Expected: `37 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `677 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): WebSocket, agendador de varreduras, tarefa diária e limpeza" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 12: Ficha pública do motoqueiro e informação da fila

Dois acertos de contrato que o app do passageiro precisa: a ficha do motoqueiro vai sem a chave interna da foto (com o endereço da foto) e quem está na fila vê onde a moto termina a corrida de agora e em quanto tempo chega (spec, seção 5.2).

**Files:**
- Modify: `server/app/api/views.py`
- Modify: `server/app/db/queries.py`
- Modify: `server/app/services/dispatch.py`
- Test: `server/tests/api/test_passenger_routes.py` (alterado)
- Test: `server/tests/services/test_dispatch.py` (alterado)

**Interfaces:**
- Consumes: `queries.rider_card`, `DispatchService.accept_offer`, `passenger_ride_view`.
- Produces: `RiderCard.public() -> dict` (`rider_id, name, plate, moto_model, rating, rating_count, photo_url`); `queries.queue_info(session, ride_id, rider_id) -> {"finishing_at", "eta_seconds"}`; o aviso `rider_accepted` passa a trazer `rider` (ficha pública) e `queue`; a visão do passageiro ganha `queue`.

- [ ] **Step 1: Escrever os testes que falham**

Altere `server/tests/api/test_passenger_routes.py`:

````diff
--- a/server/tests/api/test_passenger_routes.py
+++ b/server/tests/api/test_passenger_routes.py
@@ -227,3 +227,23 @@ def test_rotas_do_passageiro_sao_so_do_passageiro(client, runtime):
     ):
         assert getattr(client, metodo)(url, headers=motoqueiro.headers).status_code == 403
         assert getattr(client, metodo)(url).status_code == 401
+
+
+def test_passageiro_na_fila_ve_onde_a_moto_termina_e_quanto_falta(client, pax, session, runtime, clock):
+    from app.db.models import RiderProfileRow
+    from tests.helpers_db import add_accepted_ride, add_passenger
+
+    rider_id = online_rider(session, runtime, clock, 1, pt(100, 0))
+    add_passenger(session, "p0", "+5575900000010")
+    add_accepted_ride(session, ride_id="ride-0", passenger_id="p0", rider_id=rider_id)
+    repo.set_ride_details(
+        session, "ride-0", repo.RideDetails(pt(-2000, 0), pt(300, 0), "Origem", "Mercado", 2300, 1.0, "")
+    )
+    session.get(RiderProfileRow, rider_id).online = True
+    session.flush()
+    corrida = pedir(client, pax, cotar(client, pax)["quote_id"]).json()
+    runtime.run(lambda u: u.dispatch.accept_offer(u.session, rider_id, corrida["ride_id"], u.now))
+    ride = client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]
+    assert ride["state"] == "queued" and ride["queued"] is True
+    assert ride["queue"]["finishing_at"] == "Mercado" and ride["queue"]["eta_seconds"] > 0
+    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"]["rider_position"] is None
````

Altere `server/tests/services/test_dispatch.py`:

````diff
--- a/server/tests/services/test_dispatch.py
+++ b/server/tests/services/test_dispatch.py
@@ -157,8 +157,11 @@ def test_aceitar_corrida_pix_cria_a_cobranca_e_avisa_o_passageiro(dispatch, sess
     aviso = next(e for e in events.events if e.type == "rider_accepted")
     assert aviso.user_id == "p1"
     assert aviso.payload["pin"] == "4821" and aviso.payload["queued"] is False
-    assert aviso.payload["rider"]["plate"] == "ABC0001"
-    assert aviso.payload["pay"]["amount_cents"] == 700
+    assert aviso.payload["rider"] == {
+        "rider_id": "r1", "name": "Motoqueiro r1", "plate": "ABC0001", "moto_model": "Honda CG 160",
+        "rating": None, "rating_count": 0, "photo_url": None,
+    }                                          # a ficha pública: sem a chave interna da foto
+    assert aviso.payload["pay"]["amount_cents"] == 700 and aviso.payload["queue"] is None
     assert "ride_assigned" in tipos(events, "r1")
     assert [k for k, _ in repo.ride_events(session, "ride-1")] == ["offered", "accepted"]
 
@@ -209,6 +212,17 @@ def test_moto_terminando_recebe_pedido_para_a_fila(dispatch, session, positions,
     assert next(e for e in events.events if e.type == "rider_accepted").payload["queued"] is True
 
 
+def test_passageiro_da_fila_sabe_onde_a_moto_termina_e_quando_chega(dispatch, session, positions, events):
+    # Spec 5.2: "a moto está terminando uma corrida em [ponto] e chega em X minutos".
+    add_passenger(session)
+    _moto_terminando(session, positions)
+    add_searching_ride(session, now=AGORA)
+    dispatch.offer_next(session, "ride-1", AGORA)
+    dispatch.accept_offer(session, "r1", "ride-1", AGORA + 2)
+    fila = next(e for e in events.events if e.type == "rider_accepted").payload["queue"]
+    assert fila["finishing_at"] == "Destino" and fila["eta_seconds"] > 0
+
+
 def test_moto_que_ja_tem_corrida_na_fila_nao_recebe_outra(dispatch, session, positions):
     add_passenger(session)
     _moto_terminando(session, positions)
@@ -370,3 +384,15 @@ def test_motoqueiro_que_ficou_indisponivel_depois_da_oferta_nao_consegue_aceitar
     with pytest.raises(OfferGone, match="disponível"):
         dispatch.accept_offer(session, "r1", "ride-1", AGORA + 3)
     assert repo.get_ride(session, "ride-1").state is RideState.SEARCHING
+
+
+def test_ficha_publica_aponta_para_a_selfie_quando_ela_existe(session, positions):
+    from app.db import queries
+    from app.db.models import RiderProfileRow
+
+    mundo(session, positions, n_motos=1)
+    assert queries.rider_card(session, "r1").public()["photo_url"] is None
+    session.get(RiderProfileRow, "r1").selfie_key = "r1/selfie-0123456789abcdef.jpg"
+    session.flush()
+    ficha = queries.rider_card(session, "r1").public()
+    assert ficha["photo_url"] == "/v1/riders/r1/documents/selfie" and "selfie_key" not in ficha
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/api/test_passenger_routes.py tests/services/test_dispatch.py`
Expected: FAIL — `4 failed, 54 passed` (primeiro erro: `KeyError: 'queue'`).

- [ ] **Step 3: Implementar**

Altere `server/app/api/views.py`:

````diff
--- a/server/app/api/views.py
+++ b/server/app/api/views.py
@@ -62,12 +62,7 @@ def passenger_ride_view(unit: Unit, ride_id: str) -> dict:
     rider = None
     position = None
     if ride.rider_id is not None:
-        card = queries.rider_card(unit.session, ride.rider_id)
-        rider = {
-            "rider_id": card.rider_id, "name": card.name, "plate": card.plate, "moto_model": card.moto_model,
-            "rating": card.rating, "rating_count": card.rating_count,
-            "photo_url": f"/v1/riders/{card.rider_id}/documents/selfie" if card.selfie_key else None,
-        }
+        rider = queries.rider_card(unit.session, ride.rider_id).public()
         if ride.state in _WITH_RIDER_ON_THE_MOVE:
             found = unit.positions.get(ride.rider_id)
             position = None if found is None else {"lat": found.lat, "lng": found.lng}
@@ -78,6 +73,7 @@ def passenger_ride_view(unit: Unit, ride_id: str) -> dict:
         "pickup": place(details.pickup.lat, details.pickup.lng, details.pickup_text),
         "destination": place(details.destination.lat, details.destination.lng, details.destination_text),
         "distance_m": details.distance_m, "rider": rider, "rider_position": position,
+        "queue": queries.queue_info(unit.session, ride.ride_id, ride.rider_id) if ride.state is RideState.QUEUED else None,
         "pay": _pix_to_pay(unit, ride), "end_payment": _end_payment(unit, ride),
     }
 
````

Altere `server/app/db/queries.py`:

````diff
--- a/server/app/db/queries.py
+++ b/server/app/db/queries.py
@@ -24,6 +24,14 @@ class RiderCard:
     rating_count: int
     selfie_key: str | None
 
+    def public(self) -> dict:
+        """O que o app do passageiro recebe: a foto vem por endereço (com login), nunca pela chave interna."""
+        return {
+            "rider_id": self.rider_id, "name": self.name, "plate": self.plate, "moto_model": self.moto_model,
+            "rating": self.rating, "rating_count": self.rating_count,
+            "photo_url": f"/v1/riders/{self.rider_id}/documents/selfie" if self.selfie_key else None,
+        }
+
 
 def rider_card(session: Session, rider_id: str) -> RiderCard:
     found = session.execute(
@@ -409,3 +417,15 @@ def list_safety_alerts(session: Session, status: str, limit: int, offset: int) -
         )
         for a, passenger_name, rider_name, plate in rows
     ]
+
+
+def queue_info(session: Session, ride_id: str, rider_id: str) -> dict:
+    """Para o passageiro da fila: onde a moto termina a corrida de agora e em quanto tempo chega até ele."""
+    active_id = rider_active_ride_id(session, rider_id)
+    finishing_at = None
+    if active_id is not None:
+        finishing_at = session.execute(select(RideRow.dest_text).where(RideRow.id == active_id)).scalar_one_or_none()
+    eta = session.execute(
+        select(RideOfferRow.eta_seconds).where(RideOfferRow.ride_id == ride_id, RideOfferRow.status == "accepted")
+    ).scalar_one_or_none()
+    return {"finishing_at": finishing_at or "", "eta_seconds": eta}
````

Altere `server/app/services/dispatch.py`:

````diff
--- a/server/app/services/dispatch.py
+++ b/server/app/services/dispatch.py
@@ -174,7 +174,8 @@ class DispatchService:
             ride.passenger_id, "rider_accepted",
             {
                 "ride_id": ride_id, "queued": busy, "pin": ride.pin,
-                "rider": dataclasses.asdict(card),
+                "queue": queries.queue_info(session, ride_id, rider_id) if busy else None,
+                "rider": card.public(),
                 "pay": None if charge is None else {
                     "charge_id": charge.charge_id, "amount_cents": charge.amount_cents,
                     "expires_at": now + self.cfg.rides.pix_window_s,
````

- [ ] **Step 4: Rodar os testes da tarefa e ver passar**

Run: `.venv/bin/pytest -q tests/api/test_passenger_routes.py tests/services/test_dispatch.py`
Expected: `58 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: `680 passed` (nenhum teste antigo quebra; o total inclui os das tarefas anteriores).

- [ ] **Step 6: Commit**

```bash
cd .. && git add server && git commit -m "feat(api): ficha pública do motoqueiro e informação da fila" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 13: Servidor de verdade: ponto de entrada, cenário do dia pela API e documentação

Fecha o plano: `app/main.py` (como subir), o cenário de um dia inteiro pela API (cadastro com fotos, aprovação, Pix, parada longa, bloqueio e pagamento atrasado, entrada de R$ 50, livro-caixa fechando), o script que sobe o servidor de verdade com WebSocket real, `docs/api-v1.md`, o README e o roteiro.

**Files:**
- Create: `server/app/main.py`
- Create: `server/scripts/smoke_server.py`
- Test: `server/tests/api/test_dia_pela_api.py` (novo)
- Test: `server/tests/test_main.py` (novo)
- Create: `docs/api-v1.md`
- Modify: `server/README.md`, `.gitignore`, `server/.env` (fora do git)
- Modify: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`

**Interfaces:**
- Consumes: tudo das tarefas anteriores.
- Produces: `app.main.create_default_app()`; `server/scripts/smoke_server.py`; `docs/api-v1.md`; README do servidor atualizado; roteiro dos planos atualizado.

- [ ] **Step 1: Escrever os testes que falham**

Crie `server/tests/api/test_dia_pela_api.py`:

````python
"""Um dia de ponta a ponta usando só a API, o aviso do provedor assinado, o WebSocket e as varreduras."""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

from app.api.webhook import SIGNATURE_HEADER, sign
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.clock import local_date
from app.scheduler import sweep_once
from tests.api.conftest import WEBHOOK_SECRET
from tests.api.helpers import login
from tests.helpers import ORIGIN, pt
from tests.helpers_db import make_cpf

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
_pool = ThreadPoolExecutor(max_workers=2)


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


def test_um_dia_inteiro_pela_api(client, runtime, session, clock, listen):
    def webhook(evento):
        corpo = json.dumps(evento).encode()
        return client.post("/v1/webhooks/pix", content=corpo, headers={SIGNATURE_HEADER: sign(WEBHOOK_SECRET, corpo)})

    def posicao(ponto=pt(300, 0)):
        client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers)

    def pedir(metodo):
        posicao()                                                      # a posição precisa estar fresca
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers)
        assert quote.status_code == 200, quote.text
        corrida = client.post(
            "/v1/passenger/rides", json={"quote_id": quote.json()["quote_id"], "method": metodo}, headers=pax.headers
        ).json()
        assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers).status_code == 200
        return corrida

    def percurso(corrida, parar_s=0):
        rid = corrida["ride_id"]
        client.post(f"/v1/rider/rides/{rid}/arrive", headers=rider.headers)
        client.post(f"/v1/rider/rides/{rid}/helmet", headers=rider.headers)
        assert client.post(f"/v1/rider/rides/{rid}/start", json={"pin": corrida["pin"]}, headers=rider.headers).status_code == 200
        for _ in range(parar_s // 4):
            clock.advance(4)
            posicao(pt(500, 3))
        clock.advance(60)
        return client.post(f"/v1/rider/rides/{rid}/complete", headers=rider.headers).json()

    # 1) pessoas: o administrador existe; o motoqueiro se cadastra com fotos; o dono aprova
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    admin = login(client, runtime, "75 99999-0000", "admin")
    rider = login(client, runtime, "75 99777-0002", "rider")
    pax = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    hoje = local_date(clock.now)
    chaves = {
        campo: client.put(f"/v1/rider/documents/{kind}", content=JPEG, headers=rider.headers).json()["key"]
        for campo, kind in (("selfie_key", "selfie"), ("cnh_photo_key", "cnh"), ("crlv_key", "crlv"))
    }
    registro = client.post(
        "/v1/rider/register",
        json={
            "name": "Carlos Moto", "cpf": make_cpf("123456789"), "cnh_number": "12345678901", "plate": "ABC1D23",
            "moto_model": "Honda CG 160", "cnh_expires_on": str(hoje + dt.timedelta(days=700)),
            "crlv_expires_on": str(hoje + dt.timedelta(days=300)), **chaves,
        },
        headers=rider.headers,
    )
    assert registro.status_code == 201
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "pending"
    assert client.post("/v1/rider/online", headers=rider.headers).json()["error"]["code"] == "not_approved"
    fila = client.get("/v1/admin/riders", headers=admin.headers).json()
    assert [r["name"] for r in fila] == ["Carlos Moto"]
    assert client.get(f"/v1/riders/{rider.user_id}/documents/cnh", headers=admin.headers).content == JPEG
    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers).status_code == 204
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    client.put("/v1/passenger/emergency-contact", json={"name": "Maria", "phone": "75 98888-7777"}, headers=pax.headers)
    avisos_pax, avisos_rider, avisos_admin = listen(pax.user_id), listen(rider.user_id), listen(admin.user_id)

    # 2) corrida 1, Pix: pedido, aceite, pagamento assinado, parada longa, "tudo bem", fim e notas
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": pax.token})
        assert _pool.submit(ws.receive_json).result(timeout=3)["type"] == "ready"
        corrida1 = pedir("pix")
        cobranca1 = repo.get_current_charge_id(session, corrida1["ride_id"])
        assert webhook(runtime.provider.mark_paid(cobranca1)).json() == {"status": "applied"}
        fim1 = percurso(corrida1, parar_s=200)
        assert fim1["state"] == "completed" and fim1["end_payment"] is None
        alerta = next(m for m in avisos_pax.messages if m["type"] == "safety_check")["data"]
        assert client.post(
            f"/v1/rides/{corrida1['ride_id']}/safety/{alerta['alert_id']}/ok", headers=pax.headers
        ).status_code == 204
        vistos = []
        while "trip_completed" not in vistos:           # tudo isso também chegou pelo WebSocket, na ordem
            vistos.append(_pool.submit(ws.receive_json).result(timeout=3)["type"])
        assert [t for t in vistos if t != "rider_position"] == [
            "rider_accepted", "pix_confirmed", "rider_arrived", "trip_started", "safety_check", "trip_completed",
        ]
    assert client.post(f"/v1/rides/{corrida1['ride_id']}/rating", json={"stars": 5}, headers=pax.headers).status_code == 204
    assert client.post(f"/v1/rides/{corrida1['ride_id']}/rating", json={"stars": 4}, headers=rider.headers).status_code == 204
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None

    # 3) corrida 2, dinheiro: ninguém paga; passam 5 minutos; o passageiro é bloqueado; paga atrasado pelo QR
    corrida2 = pedir("cash")
    fim2 = percurso(corrida2)
    qr2 = fim2["end_payment"]["charge_id"]
    assert qr2 and client.get(f"/v1/charges/{qr2}", headers=pax.headers).json()["amount_cents"] == corrida2["price_cents"]
    clock.advance(301)
    assert sweep_once(runtime).cash_blocked == 1
    assert "payment_pending" in avisos_pax.types and "passenger_blocked" in avisos_rider.types
    estado_pax = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado_pax["pending_payment"]["blocked"] is True and "Falta pagar" in estado_pax["blocked_reason"]
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).status_code == 403
    assert webhook(runtime.provider.mark_paid(qr2)).json() == {"status": "applied"}
    assert "unblocked" in avisos_pax.types and avisos_rider.messages[-1]["data"]["late"] is True
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).status_code == 200

    # 4) corrida 3 (a 10ª): paga na mão; o motoqueiro precisa pagar a entrada de R$ 50 para continuar
    acc = repo.get_rider_account(session, rider.user_id, for_update=True)
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    corrida3 = pedir("cash")
    percurso(corrida3)
    assert client.post(f"/v1/rider/rides/{corrida3['ride_id']}/cash-received", headers=rider.headers).status_code == 204
    assert "entry_required" in avisos_rider.types and session.get(RiderProfileRow, rider.user_id).online is False
    assert client.post("/v1/rider/online", headers=rider.headers).json()["error"]["code"] == "entry_pending"
    entrada = client.post("/v1/rider/entry-charge", headers=rider.headers).json()
    assert client.post(f"/v1/dev/pix/{entrada['charge_id']}/pay").json() == {"status": "applied"}
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    conta = client.get("/v1/rider/state", headers=rider.headers).json()["account"]
    assert (conta["completed_rides"], conta["entry_paid"], conta["cash_debt_cents"], conta["needs_entry"]) == (
        10, True, 100, False,
    )

    # 5) o livro-caixa fecha e bate com o extrato do provedor; o dono viu o alerta e a nota do motoqueiro subiu
    livro = PgLedger(session)
    assert livro.is_balanced() is True
    p1, p2 = corrida1["price_cents"], corrida2["price_cents"]
    assert livro.balance(f"rider:{rider.user_id}") == (p1 - 100) + (p2 - 100)
    assert livro.balance(PgLedger.COMPANY) == 100 + 100 + 5000
    assert livro.balance(PgLedger.PROVIDER) == -(p1 + p2 + 5000)
    extrato = {
        (f"entry:{c.rider_id}" if c.purpose == "entry" else f"charge:{c.charge_id}"): c.amount_cents
        for c in runtime.provider.charges.values()
        if c.paid and not c.refunded
    }
    assert livro.reconcile(extrato) == {}
    assert avisos_admin.types.count("safety_alert") == 1
    assert client.get("/v1/rider/state", headers=rider.headers).json()["registration"]["rating"] == 5.0
````

Crie `server/tests/test_main.py`:

````python
from fastapi import FastAPI

import app.main as main


def test_fabrica_do_servidor_liga_o_agendador(monkeypatch, settings):
    import dataclasses

    chamadas = {}
    pronta = dataclasses.replace(settings, mode="dev", webhook_secret="segredo")
    monkeypatch.setattr(main, "load_settings", lambda: pronta)
    monkeypatch.setattr(main, "build_runtime", lambda s: ("runtime-de-mentira", s))

    def create_app_falso(runtime, **kwargs):
        chamadas.update(runtime=runtime, **kwargs)
        return FastAPI()

    monkeypatch.setattr(main, "create_app", create_app_falso)
    assert isinstance(main.create_default_app(), FastAPI)
    assert chamadas == {"runtime": ("runtime-de-mentira", pronta), "run_background": True}
````

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest -q tests/test_main.py`
Expected: erro ao carregar o teste — `ModuleNotFoundError: No module named 'app.main'`.

Run: `.venv/bin/pytest -q tests/api/test_dia_pela_api.py`
Expected: `1 passed` (o cenário do dia só junta peças que já existem; é um teste de ponta a ponta, não de código novo — mas é ele que prova que o conjunto fecha).

- [ ] **Step 3: Implementar**

Crie `server/app/main.py`:

````python
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
````


Crie `server/scripts/smoke_server.py`:

````python
"""Sobe o servidor de verdade (uvicorn) num esquema temporário do banco e confere o caminho completo de um app:
saúde, login, WebSocket, preço e uma volta do agendador.

Uso (a partir de `server/`):  PYTHONPATH=. .venv/bin/python scripts/smoke_server.py

Usa o PostgreSQL e o Redis de desenvolvimento, mas só o esquema `t_...` criado aqui (apagado no fim) e o banco
número 14 do Redis (esvaziado no fim). Sai com código diferente de zero se algo falhar.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote

import httpx2 as httpx
import redis
import websockets
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.settings import load_settings


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    settings = load_settings()
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema},public"})
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        cfg.attributes["schema"] = schema
        command.upgrade(cfg, "head")
    engine.dispose()

    port, uploads = free_port(), tempfile.mkdtemp(prefix="smoke-uploads-")
    redis_url = settings.redis_url.rsplit("/", 1)[0] + "/14"
    separator = "&" if "?" in settings.database_url else "?"
    env = dict(
        os.environ,
        DATABASE_URL=settings.database_url + separator + "options=" + quote(f"-csearch_path={schema},public"),
        REDIS_URL=redis_url, APP_MODE="dev", WEBHOOK_SECRET="segredo-do-smoke", UPLOAD_DIR=uploads,
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", "app.main:create_default_app", "--port", str(port),
         "--log-level", "warning"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.25)
        else:
            raise SystemExit("o servidor não subiu")
        client = httpx.Client(base_url=base, timeout=5)
        assert client.get("/health").json() == {"status": "ok"}
        print("OK saúde: banco e Redis respondem")

        phone = "75 99999-0001"
        assert client.post("/v1/auth/code", json={"phone": phone}).status_code == 204
        code = client.get("/v1/dev/otp", params={"phone": phone}).json()["code"]
        login = client.post("/v1/auth/verify", json={"phone": phone, "code": code, "role": "passenger"}).json()
        headers = {"Authorization": f"Bearer {login['token']}"}
        assert client.put("/v1/me", json={"name": "Ana Lima"}, headers=headers).json()["name"] == "Ana Lima"
        print("OK login por código e nome")

        async def websocket_flow() -> None:
            async with websockets.connect(f"ws://127.0.0.1:{port}/v1/ws") as ws:
                await ws.send(json.dumps({"token": login["token"]}))
                assert json.loads(await ws.recv())["type"] == "ready"
                await ws.send("ping")
            async with websockets.connect(f"ws://127.0.0.1:{port}/v1/ws") as ws:
                await ws.send(json.dumps({"token": "inventado"}))
                try:
                    await asyncio.wait_for(ws.recv(), 3)
                except websockets.ConnectionClosed as closed:
                    assert closed.rcvd.code == 4401
                else:
                    raise AssertionError("token ruim deveria fechar a conexão")

        asyncio.run(websocket_flow())
        print("OK WebSocket: token bom conecta, token ruim fecha com 4401")

        quote_body = {
            "pickup": {"lat": -12.9644, "lng": -39.2597, "text": "A"},
            "destination": {"lat": -12.95, "lng": -39.25, "text": "B"},
        }
        price = client.post("/v1/passenger/quotes", json=quote_body, headers=headers).json()
        assert price["price_cents"] > 0 and "cash" in price["payment_methods"]
        print(f"OK preço: R$ {price['price_cents'] / 100:.2f}")

        time.sleep(4)          # deixa o agendador dar pelo menos uma volta
        assert server.poll() is None, "o servidor caiu"
    finally:
        server.terminate()
        output = server.communicate(timeout=10)[0]
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        shutil.rmtree(uploads, ignore_errors=True)
        redis.Redis.from_url(redis_url).flushdb()
    bad = [line for line in output.splitlines() if "Traceback" in line or "ERROR" in line]
    assert not bad, "erros no registro do servidor:\n" + "\n".join(bad)
    print("OK agendador rodou sem erros no registro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
````

- [ ] **Step 4: Rodar os testes novos**

Run: `.venv/bin/pytest -q tests/test_main.py tests/api/test_dia_pela_api.py`
Expected: `2 passed`

- [ ] **Step 5: Preparar o ambiente de desenvolvimento (`.env` e `.gitignore`)**

Run (sem mostrar o conteúdo do arquivo):
```bash
printf 'APP_MODE=dev\nWEBHOOK_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
grep -c '^WEBHOOK_SECRET=' .env; grep -c '^APP_MODE=dev' .env; stat -c %a .env
```
Expected: `1`, `1` e `600` (um segredo novo, o modo dev, e o arquivo continua só do dono). Nunca imprima nem envie o `.env`.

Acrescente a linha `server/var/` ao `.gitignore` da raiz do repositório (as fotos dos documentos ficam em `server/var/uploads`):

```diff
 .superpowers/
 server/.venv/
+server/var/
 __pycache__/
 .pytest_cache/
 .env
```

- [ ] **Step 6: Escrever a documentação**

Crie `docs/api-v1.md` (na raiz do repositório, não em `server/`) com o conteúdo abaixo, e **substitua** `server/README.md` pelo segundo bloco.

````markdown
# API do servidor, versão 1

Contrato que os apps (planos 5 e 6), o painel (plano 4) e o simulador (plano 3) usam. Em modo de desenvolvimento
(`APP_MODE=dev`) o servidor também publica a descrição gerada automaticamente em `/docs` e `/openapi.json`.

## Convenções

- Tudo em `/v1`, JSON em UTF-8. Entrar: `Authorization: Bearer <token>` em toda rota, menos as de login e o aviso do provedor.
- **Dinheiro em centavos inteiros.** Horas em segundos Unix (`float`). Datas `AAAA-MM-DD`. Coordenadas `{"lat", "lng"}`.
- Erro: `{"error": {"code": "...", "message": "..."}}` (às vezes com `field` ou `fields`). O app decide pelo `code`,
  que é estável; a `message` é uma frase em português para mostrar à pessoa.
- Cada papel só usa as suas rotas: `passenger`, `rider` ou `admin` (`403 wrong_role` nas outras).
- Os avisos em tempo real (WebSocket) são **dicas**. A fonte da verdade é `GET /v1/passenger/state` e
  `GET /v1/rider/state`: ao abrir o app, ao reconectar e ao receber `ready`, peça o estado de novo.

## Entrar e conta

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /v1/auth/code` | `{"phone"}` | 204. Envia o código de 6 dígitos (WhatsApp no plano 7). 429 se pediu demais. |
| `POST /v1/auth/verify` | `{"phone","code","role","device"?}` | `{"token","user_id","role","is_new_user","name"}`. 401 `code_invalid` com a frase do motivo. |
| `POST /v1/auth/logout` | | 204 |
| `GET /v1/me` | | `{"user_id","phone","name","role"}` |
| `PUT /v1/me` | `{"name"}` | o mesmo de `GET /v1/me` |

A sessão dura 180 dias. `role: "admin"` só entra se o número já foi criado com `python -m app.cli create-admin`.

## Passageiro

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /v1/passenger/quotes` | `{"pickup": {lat,lng,text}, "destination": {lat,lng,text}}` | preço: `quote_id, price_cents, reason, distance_m, duration_s, expires_at, pickup, destination, eta_seconds` (estimativa, `null` sem moto livre), `nearby_riders`, `payment_methods` (`["pix","cash"]`, ou só `["cash"]` com o Pix fora do ar) |
| `POST /v1/passenger/rides` | `{"quote_id","method": "pix"\|"cash"}` | 201 com a corrida (abaixo) |
| `POST /v1/passenger/rides/{id}/cancel` | | `{"refund": bool}` |
| `GET /v1/passenger/state` | | `{"ride", "pending_payment", "blocked_reason", "unpaid_cents", "emergency_contact", "payment_methods"}` |
| `PUT /v1/passenger/emergency-contact` | `{"name","phone"}` | 204. Não pode ser o número do próprio passageiro. |
| `POST /v1/rides/{id}/rating` | `{"stars": 1..5}` | 204 (vale para os dois lados, depois que a corrida acabou) |
| `POST /v1/rides/{id}/sos` | | `{"alert_id","contact_registered","contact_notified","repeated","emergency_number": "190"}` |
| `POST /v1/rides/{id}/safety/{alert_id}/ok` | | 204 ("está tudo bem" ao aviso automático) |

**Corrida (visão do passageiro):** `ride_id, state` (`searching, queued, accepted, arrived, in_progress`),
`queued, price_cents, price_reason, method, pin` (os 4 dígitos que ele diz ao motoqueiro), `helmet_confirmed, pix_paid,
pickup, destination, distance_m, rider` (`rider_id, name, plate, moto_model, rating, rating_count, photo_url`),
`rider_position` (`{lat,lng}` ou `null`), `queue` (`{"finishing_at","eta_seconds"}` quando está na fila),
`pay` (`{"charge_id","amount_cents","expires_at"}` enquanto o Pix não foi pago) e `end_payment`.
`photo_url` é uma rota com login: `GET /v1/riders/{id}/documents/selfie`.

`pending_payment` (corrida em dinheiro terminada e sem pagamento): `{"ride_id","amount_cents","charge_id","blocked"}`.
Com `blocked: true` o passageiro não pede outra corrida até pagar o QR (`charge_id`).

## Cobrança (QR do Pix)

`GET /v1/charges/{charge_id}` → `{"charge_id","purpose","ride_id","amount_cents","paid","br_code"}`.
`purpose`: `ride` (Pix antes da corrida), `end` (QR do fim da corrida em dinheiro) ou `entry` (entrada do motoqueiro).
O app desenha o QR a partir de `br_code`. Vê quem participa da corrida (passageiro e motoqueiro) e o administrador;
a entrada, só o motoqueiro.

## Motoqueiro

| Rota | Corpo | Resposta |
|---|---|---|
| `PUT /v1/rider/documents/{selfie\|cnh\|crlv}` | a foto crua (JPEG, PNG ou WebP, até 8 MB) | 201 `{"key","bytes"}` |
| `POST /v1/rider/register` | nome, CPF, CNH, placa, modelo, validade da CNH e do documento da moto, `selfie_key`, `cnh_photo_key`, `crlv_key` | 201 `{"status":"pending"}` |
| `POST /v1/rider/documents/renew` | `{"cnh_expires_on","crlv_expires_on","cnh_photo_key"?,"crlv_key"?}` | 204 |
| `GET /v1/rider/state` | | `{"registration","account","offer","ride","queued_ride","awaiting_payment"}` |
| `POST /v1/rider/online` · `/offline` | | 204. 409 com o `code` do motivo (`not_approved`, `blocked`, `documents_expired`, `entry_pending`) |
| `POST /v1/rider/position` | `{"lat","lng"}` | 204. A cada ~4 s enquanto disponível (e durante a corrida). |
| `POST /v1/rider/entry-charge` | | 201 `{"charge_id","amount_cents","br_code"}` (a entrada de R$ 50) |
| `POST /v1/rider/offers/{ride_id}/accept` | | a corrida (visão do motoqueiro) |
| `POST /v1/rider/offers/{ride_id}/decline` | | 204, sem penalidade |
| `POST /v1/rider/rides/{id}/arrive` · `/helmet` · `/complete` | | a corrida |
| `POST /v1/rider/rides/{id}/start` | `{"pin": "1234"}` | a corrida. 422 `wrong_pin`; depois de 5 erros em 10 min, 429. |
| `POST /v1/rider/rides/{id}/cash-received` | | 204 (recebi o dinheiro na mão) |

**Corrida (visão do motoqueiro):** `ride_id, state, queued, price_cents, fee_cents, method, pix_paid, helmet_confirmed,
passenger` (`{"name"}`, só o primeiro nome), `pickup, destination, distance_m` e `end_payment`
(`{"charge_id","amount_cents","blocked"}` enquanto a corrida em dinheiro espera pagamento).

**Estado do motoqueiro:** `registration` (`status`: `not_registered, pending, approved, rejected, blocked`; `online`,
`reason`, `rating`, `rating_count`, validades), `account` (`completed_rides, trial_rides, entry_paid, entry_fee_cents,
needs_entry, cash_debt_cents, cash_debt_limit_cents`), `offer` (a oferta pendente, no mesmo formato do aviso `offer`),
`ride` (andando), `queued_ride` e `awaiting_payment`.

## Documentos

`GET /v1/riders/{rider_id}/documents/{selfie|cnh|crlv}` devolve a imagem. Vê tudo: o administrador e o próprio
motoqueiro. O passageiro vê só a `selfie`, de um motoqueiro que já aceitou uma corrida dele.

## Administrador (o painel completo é o plano 4)

| Rota | |
|---|---|
| `GET /v1/admin/riders?status=pending\|approved\|blocked\|rejected&limit&offset` | fila de cadastros |
| `POST /v1/admin/riders/{id}/approve` · `/unblock` | 204 |
| `POST /v1/admin/riders/{id}/reject` · `/block` | `{"reason"}` → 204 |
| `GET /v1/admin/safety-alerts?status=open\|ok\|sos\|resolved` | alertas com nomes, placa e posição |
| `POST /v1/admin/safety-alerts/{id}/resolve` | `{"note"?}` → 204 |

## Aviso do provedor de pagamento

`POST /v1/webhooks/pix`, sem login. O corpo é JSON `{"event_id","type":"paid","charge_id","ride_id","amount_cents"}` e
a assinatura vai no cabeçalho `x-signature: sha256=<HMAC-SHA256 do corpo com WEBHOOK_SECRET>`. Resposta
`{"status": "applied"|"refunded"|"duplicate"|"unknown_charge"}`. Valor ou corrida diferentes da cobrança guardada: 409
`event_mismatch` (o aviso não é gasto). O adaptador da Woovi (plano 7) traduz o aviso dela para este formato.

## Só em desenvolvimento (`APP_MODE=dev`)

`GET /v1/dev/otp?phone=...` devolve o último código de login enviado; `POST /v1/dev/pix/{charge_id}/pay` faz de conta
que o passageiro pagou o Pix (passa pelo mesmo caminho do aviso real). Em produção estas rotas não existem.

## Tempo real (WebSocket)

Conectar em `/v1/ws`. A **primeira mensagem** é `{"token": "..."}` (o token não vai na URL). Resposta:
`{"type":"ready","data":{"user_id","role"},"at":...}`. Depois chegam avisos `{"type","data","at"}`. Token ruim ou
ausente em 10 s: o servidor fecha com o código **4401**. Fila cheia (o app não está lendo): fecha com **4408**.
Nos dois casos, reconecte e peça o estado. O app pode mandar texto qualquer (`"ping"`) para manter a conexão viva.

| Aviso | Para | `data` |
|---|---|---|
| `offer` | motoqueiro | `ride_id, price_cents, payment_method, pickup, destination, distance_m, seconds_to_pickup, will_queue, expires_at` |
| `offer_expired` | motoqueiro | `ride_id` |
| `ride_assigned` | motoqueiro | `ride_id, queued` |
| `next_ride` | motoqueiro | `ride_id` (a corrida da fila começou) |
| `ride_cancelled` | os dois | `ride_id` e `by: "passenger"` ou `reason: "pix_expired"\|"arrival_wait"` |
| `rider_accepted` | passageiro | `ride_id, queued, pin, queue, rider, pay` |
| `rider_on_the_way` | passageiro | `ride_id` (a corrida da fila começou) |
| `rider_arrived` · `trip_started` | passageiro | `ride_id` |
| `rider_position` | passageiro | `ride_id, lat, lng` |
| `trip_completed` | os dois | `ride_id, price_cents, method, pay` |
| `no_rider` | passageiro | `ride_id` |
| `queue_released` | passageiro | `ride_id, refunded` |
| `pix_confirmed` | passageiro | `ride_id, amount_cents` |
| `payment_received` | motoqueiro | `ride_id, late` |
| `payment_refunded` | passageiro | `ride_id, amount_cents` |
| `qr_ready` | os dois | `ride_id, charge_id, amount_cents` (o QR do fim da corrida em dinheiro) |
| `payment_confirmed` | passageiro | `ride_id` (o motoqueiro confirmou o dinheiro) |
| `payment_pending` | passageiro | `ride_id, amount_cents, charge_id` (passou o prazo sem pagar: pague o QR) |
| `passenger_blocked` | motoqueiro | `ride_id` (o passageiro foi bloqueado; você está livre) |
| `unblocked` | passageiro | `ride_id` |
| `entry_required` · `entry_paid` | motoqueiro | `entry_fee_cents` · sem dados |
| `rider_approved` · `rider_rejected` · `rider_blocked` · `rider_unblocked` · `documents_expired` | motoqueiro | `reason` quando houver |
| `safety_check` | passageiro | `ride_id, alert_id, kind` (`stopped` ou `off_route`): "está tudo bem?" |
| `sos_sent` | passageiro | `alert_id, contact_registered, contact_notified` |
| `safety_alert` · `safety_ok` · `sos` · `mock_location_suspected` | administradores | dados do alerta e da corrida |

## Códigos de erro

`unauthorized` 401 · `wrong_role` 403 · `forbidden` 403 · `not_found` 404 · `invalid` 422 (`fields` lista os campos) ·
`not_allowed` 403 · `quote_expired` 409 · `offer_gone` 409 · `not_your_ride` 403 · `already_rated` 409 ·
`invalid_state` 409 · `alert_closed` 409 · `duplicate_registration` 409 (`field`) · `not_approved`, `blocked`,
`documents_expired`, `entry_pending` 409 · `wrong_pin` 422 · `code_invalid` 401 · `too_many_requests` 429 ·
`payment_unavailable` 503 · `bad_signature` 401 · `event_mismatch` 409 · `file_too_large`/`too_large` 413 ·
`not_an_image` 415 · `empty_file` 422 · `http_404`/`http_405` · `internal` 500.

## Operação

- **Um processo só** (`--workers 1`): o hub do WebSocket e o agendador vivem dentro dele. Mais de um processo precisa de
  um canal entre eles (por exemplo, Redis pub/sub) e de uma trava para o agendador; isso não existe ainda.
- Atrás de um proxy (nginx), suba com `--proxy-headers --forwarded-allow-ips='*'` só se o servidor ficar acessível
  exclusivamente pelo proxy, para o limite de pedidos de código por aparelho enxergar o IP verdadeiro. O proxy também
  deve limitar o tamanho do corpo dos pedidos (as rotas de foto e de aviso já cortam o que passa do limite).
- O servidor recusa subir sem `APP_MODE=dev` até o plano 7 trazer os adaptadores reais.
````

README do servidor:

````markdown
# Servidor do app de corrida

Núcleo de regras (plano 1), banco, Redis e fluxo de dinheiro (plano 2A), serviços da corrida (plano 2B) e API com
tempo real (plano 2C). Dinheiro sempre em centavos inteiros. O contrato da API está em `docs/api-v1.md`.

## Pré-requisitos

- Python 3.12, PostgreSQL 16 com PostGIS e Redis rodando (`systemctl is-active postgresql redis-server`).
- `server/.env` com `DATABASE_URL`, `REDIS_URL`, `APP_MODE=dev` e `WEBHOOK_SECRET` (o arquivo é ignorado pelo git; nunca o envie).
  Opcional: `UPLOAD_DIR` (onde ficam as fotos dos documentos; por padrão `server/var/uploads`, também fora do git).

## Instalar e rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8" "httpx2>=2.0" "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" \
        "redis>=5.0" tzdata "fastapi>=0.115" "uvicorn[standard]>=0.30"
    .venv/bin/pytest -q

Os testes de banco criam um esquema temporário (`t_...`) no banco de desenvolvimento, aplicam as
migrações nele e o apagam no fim. Se um teste for interrompido à força, sobra um esquema `t_...`;
apague com `DROP SCHEMA "t_..." CASCADE`. O Redis dos testes é o banco número 15.

## Migrações

    .venv/bin/alembic upgrade head      # aplica no banco de desenvolvimento
    .venv/bin/alembic current           # mostra a versão atual

## Rodar o servidor (desenvolvimento)

    .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy"    # uma vez
    .venv/bin/uvicorn --factory app.main:create_default_app --port 8000                # um processo só

- Sem WhatsApp e sem Pix de verdade ainda (plano 7): o código de login aparece no registro do servidor e em
  `GET /v1/dev/otp?phone=...`; um Pix é "pago" com `POST /v1/dev/pix/{charge_id}/pay`.
- `http://127.0.0.1:8000/docs` mostra todas as rotas; `http://127.0.0.1:8000/health` confere banco e Redis.
- O agendador roda dentro do servidor: varredura de tempo a cada 3 s, checagem diária de documentos vencidos e limpeza
  das posições que sumiram (a cada minuto).

## Mapa do código

- `app/domain/` — regras de negócio puras (preço, taxa, dívida, divisão, livro-caixa em memória, corrida, escolha da moto, segurança).
- `app/db/` — modelos, repositórios, consultas (`queries.py`), livro-caixa persistente (`pg_ledger.py`) e configuração no banco (`config_store.py`).
- `app/infra/` — Redis (posições, reservas, fator de preço, limite de tentativas, saúde do Pix, marcas de tarefas), rastro de segurança e fotos dos documentos.
- `app/services/` — `auth`, `riders`, `quotes`, `ride_requests`, `dispatch`, `trips`, `payments`, `sweeps`, `safety`; `events.py` anota os avisos.
- `app/runtime.py` — `Runtime.run`: a unidade de trabalho de cada pedido (sessão, serviços com um `EventCollector` só, commit, depois publicação dos avisos; repete por impasse no banco).
- `app/realtime/hub.py` — conexões WebSocket e entrega dos avisos de qualquer thread.
- `app/api/` — `app.py` (montagem), `errors.py` (erros → respostas), `deps.py` (quem chama), `views.py` (como a corrida aparece), `webhook.py` (aviso assinado do provedor), `routes/` (uma pasta de rotas por assunto).
- `scripts/smoke_server.py` — sobe o servidor de verdade num esquema temporário e confere login, WebSocket e agendador (`PYTHONPATH=. .venv/bin/python scripts/smoke_server.py`; usa o Redis banco 14 e o apaga no fim).
- `app/scheduler.py` — varredura, tarefa diária e limpeza; `app/main.py` — ponto de entrada do uvicorn; `app/cli.py` — criar o administrador.
- `app/adapters/` — provedores falsos (pagamento, mapas, código de login, aviso ao contato), os únicos que existem até o plano 7.
- `migrations/` — esquema do banco (Alembic).

## Regras de convivência

- Serviços e repositórios não fazem `commit`: quem chama controla a transação (`Runtime.run` nas rotas; `sweep_once` nas varreduras).
- Os serviços recebem `now` como parâmetro e anotam avisos num `EventCollector`; ele só é publicado depois do commit. Cada unidade de trabalho tem o seu coletor: nunca compartilhe um entre pedidos.
- Login: `AuthService.verify_code` não levanta erro para código errado; devolve `ok=False` para a tentativa ser gravada (a rota responde 401 depois do commit).
- Ordem de travas: corrida, corrida da fila, motoqueiro, cobrança, passageiro.
- `save_rider_account` regrava as quatro colunas: só chame depois de ler com `for_update=True`.
- O cliente Redis é sempre criado com `decode_responses=True` (as posições recusam cliente sem isso).
````

- [ ] **Step 7: Atualizar o roteiro dos planos**

Em `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`:

1. Na tabela, troque a linha do plano 2C por:

````markdown
| 2C | **API e tempo real** (`2026-10-18-02c-api-e-tempo-real.md`) | FastAPI sobre os serviços do 2B: login, cadastro com fotos, preço, pedido, ofertas, corrida, cobrança e QR do Pix, aviso assinado do provedor, WebSocket, varredura de tempo e checagem diária rodando sozinhas, alertas de segurança com SOS, mínimo do painel (aprovar cadastros e ver alertas) e o contrato em `docs/api-v1.md`. | 2B | não |
````

2. Substitua a seção inteira `## Itens para o plano 2C` (até antes de `## Decisões já tomadas`) por:

````markdown
## Itens que sobraram do plano 2C

Do Levy decidir (o servidor segue o padrão atual):
- Compensação do cancelamento tardio: hoje só fica registrada no histórico da corrida, sem movimento de dinheiro, e a API não a promete ao app. Decidir a política (valor em aberto na spec) e como cobrar.
- Se a corrida com bloqueio por falta de pagamento conta para as 10 corridas de teste (hoje conta).

Plano 3 (simulador): usa `/v1/dev/otp` e `/v1/dev/pix/{id}/pay`; motoqueiros falsos mandam posição a cada 4 s.

Plano 4 (painel): listas de corridas, dinheiro e taxas, devedores, bloqueio de passageiro, parâmetros (`app_config`); a dívida reservada de um QR que nunca é pago continua reservada até alguém resolver; registro das ações do administrador; CORS para o site.

Planos 5 e 6 (apps): histórico de corridas e extrato do dia (rotas novas), notificação push (FCM) para oferta e avisos com o app fechado, reenvio de avisos perdidos.

Plano 7 (integrações reais): adaptadores da Woovi, do Google Maps e do WhatsApp (também para o aviso ao contato de emergência); traduzir erros de rede para `PaymentProviderError`; idempotência da chamada ao provedor (hoje dentro da transação); recriar o QR do pagamento atrasado quando ele expira (a Woovi real expira); inverter o padrão de `APP_MODE` para exigir os adaptadores reais.

Mais de um processo: exige um canal entre eles (Redis pub/sub) para o hub do WebSocket e uma trava para o agendador.

Menores do 2B que seguem abertos: o `downgrade` da migração 0002 falha se existe cobrança de entrada; a taxa da corrida da fila é fixada no aceite.
````

3. Em `## Decisões já tomadas`, acrescente: `- SOS: o servidor aceita durante toda a corrida (a caminho, na chegada e andando); mostrar o botão sempre ou só dentro do aviso automático é decisão do Levy nas telas do app (spec, seção 9, itens 4 e 5).`

- [ ] **Step 8: Suíte inteira e conferência do banco**

Run: `.venv/bin/pytest -q`
Expected: `682 passed`

Run: `.venv/bin/alembic current`
Expected: `0004 (head)`

- [ ] **Step 9: Servidor de verdade (fumaça)**

Run: `PYTHONPATH=. .venv/bin/python scripts/smoke_server.py`
Expected, nesta ordem, terminando com código 0:
```
OK saúde: banco e Redis respondem
OK login por código e nome
OK WebSocket: token bom conecta, token ruim fecha com 4401
OK preço: R$ 6.50
OK agendador rodou sem erros no registro
```
(o valor do preço pode variar com as motos online; tem que aparecer uma linha `OK preço: R$ ...`). O script cria um esquema temporário e usa o Redis banco 14; apaga os dois no fim.

- [ ] **Step 10: Conferir o que vai para o commit**

Run: `cd .. && git status --short`
Expected: só arquivos desta tarefa (`.gitignore`, `docs/api-v1.md`, `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`, `server/README.md`, `server/app/main.py`, `server/scripts/smoke_server.py`, os testes novos); **sem** `server/.env` e sem `server/var/`.

- [ ] **Step 11: Commit**

```bash
cd .. && git add server docs .gitignore && git commit -m "feat(api): ponto de entrada, cenário do dia pela API, script de fumaça e documentação" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---


---

## Itens que ficam para depois (e onde entram)

**Do Levy decidir** (o servidor segue o padrão atual): política e cobrança da compensação do cancelamento tardio; se a corrida bloqueada por falta de pagamento conta para as 10 de teste (hoje conta); quem arca com o prejuízo se o passageiro nunca pagar (hoje, o motoqueiro).

**Plano 3 (simulador):** usa `/v1/dev/otp` e `/v1/dev/pix/{id}/pay`; motoqueiros falsos mandam posição a cada 4 s.

**Plano 4 (painel):** listas de corridas, dinheiro e taxas, devedores, bloqueio de passageiro, parâmetros (`app_config`), dívida reservada de um QR que nunca é pago, registro das ações do administrador (auditoria), CORS para o site.

**Planos 5 e 6 (apps):** histórico de corridas e extrato do dia (rotas novas, o dado já existe), notificação push (FCM) para oferta e avisos com o app fechado, reenvio de avisos perdidos, o texto exato das telas.

**Plano 7 (integrações reais):** adaptadores da Woovi, do Google Maps e do WhatsApp (que também envia o aviso ao contato de emergência); traduzir erros de rede para `PaymentProviderError`; idempotência da chamada ao provedor (hoje dentro da transação); recriar o QR do pagamento atrasado quando ele expira; inverter o padrão de `APP_MODE`.

**Mais de um processo:** exige um canal entre eles (Redis pub/sub) para o hub e uma trava para o agendador.

**Menores do 2B que seguem abertos:** o `downgrade` da migração 0002 falha se existe cobrança de entrada; a taxa da corrida da fila é fixada no aceite.

## Autoavaliação (feita ao escrever o plano)

**Cobertura da spec:**
- 4 e 5.1 (telas e etapas): preço, pedido, cancelamento, avaliação, estado do passageiro (Tarefa 7); oferta, aceitar, chegada, capacete, código, fim, entrada (8); fila com "onde a moto termina e quanto falta" (12).
- 5.2 (fila): estado do motoqueiro e do passageiro mostram a corrida da fila (7, 8, 12).
- 7.2 (pagamentos): aviso assinado, cobrança com `br_code`, Pix pago e devolvido avisam os dois lados, QR do fim em dinheiro e pagamento atrasado pela API (9, 13), Pix fora do ar (9).
- 8 (cadastro): fotos, cadastro, aprovação, bloqueio automático diário por documento vencido, renovação, ficha para o passageiro (6, 11, 12).
- 9 (segurança): ficha, código de 4 dígitos com trava, capacete (8), aviso automático e SOS (10).
- 10.1, 10.2 (tempo real): WebSocket, posição a cada ~4 s (8, 11); 10.4 (login): código, sessão longa, limite por número e por aparelho (5).
- 12 (resiliência): aviso repetido (9), Pix fora do ar (9), dois pedidos para a mesma moto (índice do banco, 2 e 7), reconexão (3, 11), servidor fora do ar (`/health`, 4).

**Fora de propósito:** histórico e extrato (apps), painel completo (plano 4), push (FCM), integrações reais (plano 7), mais de um processo.

**Limitações conhecidas:** (1) o `InMemory*` dos testes e o Redis do servidor têm o mesmo contrato, mas só o Redis é exercitado pelo script de fumaça; (2) os avisos perdidos durante uma queda não são repetidos, o app pede o estado; (3) o limite por aparelho depende de o proxy repassar o IP certo (ver `docs/api-v1.md`, "Operação"); (4) a estimativa de chegada da cotação não usa o mapa.

**Varredura de lacunas e nomes:** nenhum passo tem "a definir", "tratar erros depois" ou "similar à tarefa N"; o código vem dos commits que rodaram. Os nomes usados nas tarefas seguintes (`Runtime.run`, `Unit`, `Hub`, `listen`, `login`, `online_rider`, `rider_phone`, `passenger_ride_view`, `rider_ride_view`, `process_pix_event`, `SafetyService`, `sweep_once`, `Scheduler`) são os mesmos definidos nas tarefas que os produzem.
