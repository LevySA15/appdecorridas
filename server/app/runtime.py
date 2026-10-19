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
from app.adapters.fake_notifier import FakeContactNotifier
from app.adapters.fake_otp import DevOtpSender
from app.adapters.fake_payments import FakePaymentProvider
from app.db.config_store import AppConfig, load_app_config
from app.db.session import make_engine, make_session_factory
from app.domain.maps import MapsProvider
from app.domain.notifier import ContactNotifier
from app.domain.payments import PaymentProvider
from app.api.webhook import HmacVerifier, WebhookVerifier
from app.infra.documents import DocumentStore, LocalDocumentStore
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
from app.infra.safety_store import RedisSafetyStore, SafetyStore
from app.realtime.hub import Hub
from app.services.auth import AuthService, OtpSender
from app.services.dispatch import DispatchService, Reservations
from app.services.events import EventCollector
from app.services.passenger_money import PassengerMoneyService
from app.services.payments import PaymentService
from app.services.quotes import QuoteService
from app.services.ride_requests import RideRequestService
from app.services.riders import RiderService
from app.services.safety import SafetyService
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
    positions: PositionStore
    auth: AuthService
    riders: RiderService
    payments: PaymentService
    dispatch: DispatchService
    trips: TripService
    quotes: QuoteService
    requests: RideRequestService
    sweeps: SweepService
    safety: SafetyService
    money: PassengerMoneyService


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
    documents: DocumentStore
    webhook_verifier: WebhookVerifier
    safety_store: SafetyStore
    notifier: ContactNotifier
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

    def payment_methods(self, now: float) -> list[str]:
        """O que o passageiro pode escolher agora. Com o Pix fora do ar, só dinheiro (spec, seção 12)."""
        return ["cash"] if self.pix_health.is_down(now) else ["pix", "cash"]

    # --- unidade de trabalho --------------------------------------------------------------------

    def make_unit(self, session: Session) -> Unit:
        cfg = self.config(session)
        events = EventCollector()
        payments = PaymentService(self.provider, cfg.fees, cfg.rides, events)
        dispatch = DispatchService(self.positions, self.reservations, self.maps, payments, events, cfg)
        trips = TripService(payments, dispatch, events, cfg, self.positions)
        safety = SafetyService(self.safety_store, self.positions, self.notifier, events, cfg)
        return Unit(
            session=session, now=self.clock(), cfg=cfg, events=events, positions=self.positions,
            auth=AuthService(self.otp_sender, cfg.auth),
            riders=RiderService(self.positions, events, cfg.fees),
            payments=payments, dispatch=dispatch, trips=trips,
            quotes=QuoteService(self.maps, self.positions, self.factors, cfg),
            requests=RideRequestService(dispatch, events, cfg),
            sweeps=SweepService(payments, dispatch, trips, events, cfg, safety=safety),
            safety=safety,
            money=PassengerMoneyService(payments, events, cfg),
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
    if not settings.webhook_secret:
        raise RuntimeError("falta WEBHOOK_SECRET em server/.env (assina os avisos do provedor de pagamento)")
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
        documents=LocalDocumentStore(settings.upload_dir),
        webhook_verifier=HmacVerifier(settings.webhook_secret),
        safety_store=RedisSafetyStore(client),
        notifier=FakeContactNotifier(),
        mode="dev",
        redis_client=client,
    )
