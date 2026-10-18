"""Montagem da API para os testes: banco de teste (com desfazer no fim), lojas em memória e relógio manual."""
import pytest
from fastapi.testclient import TestClient

from app.adapters.fake_maps import FakeMaps
from app.adapters.fake_notifier import FakeContactNotifier
from app.adapters.fake_otp import FakeOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.api.app import create_app
from app.api.webhook import HmacVerifier
from app.domain.dispatch import ReservationBook
from app.infra.documents import LocalDocumentStore
from app.infra.redis_store import (
    InMemoryFactorStore,
    InMemoryJobMarks,
    InMemoryPixHealth,
    InMemoryPositionStore,
    InMemoryRateLimiter,
)
from app.infra.safety_store import InMemorySafetyStore
from app.realtime.hub import Hub
from app.runtime import Runtime

AGORA = 1_800_000_000.0
WEBHOOK_SECRET = "segredo-de-teste"


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
def runtime(session, clock, tmp_path):
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
        documents=LocalDocumentStore(tmp_path / "docs"),
        webhook_verifier=HmacVerifier(WEBHOOK_SECRET),
        safety_store=InMemorySafetyStore(),
        notifier=FakeContactNotifier(),
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
