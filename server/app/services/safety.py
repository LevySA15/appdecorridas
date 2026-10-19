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
from app.domain.safety import AlertType, PositionSample, evaluate, no_signal_after_s, signal_gap_s
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

    def check_signal(self, session: Session, ride: queries.SignalRide, now: float) -> SafetyAlertRow | None:
        """A moto de uma corrida em andamento ficou tempo demais sem mandar posição? Avisa o passageiro, o contato de
        emergência e os administradores (uma vez por silêncio: o mesmo alerta só volta depois do prazo de repetição)."""
        cfg = self.cfg.safety
        gap = signal_gap_s(self.positions.last_seen(ride.rider_id), ride.started_at, now)
        if gap is None or gap < no_signal_after_s(ride.distance_m, cfg):
            return None
        if not self.store.claim(f"{ride.ride_id}:{AlertType.NO_SIGNAL.value}", now, cfg.alert_cooldown_s):
            return None
        where = self.positions.get(ride.rider_id)
        alert = SafetyAlertRow(
            ride_id=ride.ride_id, kind=AlertType.NO_SIGNAL.value, status="open",
            lat=where.lat if where else None, lng=where.lng if where else None, created_at=now,
        )
        session.add(alert)
        session.flush()
        repo.log_ride_event(session, ride.ride_id, "no_signal", {"seconds": int(gap)}, now)
        self.events.add(
            ride.passenger_id, "safety_check", {"ride_id": ride.ride_id, "alert_id": alert.id, "kind": alert.kind}
        )
        self._notify_admins(
            session, "safety_alert",
            {"alert_id": alert.id, "ride_id": ride.ride_id, "kind": alert.kind, "lat": alert.lat, "lng": alert.lng},
        )
        contact = repo.get_emergency_contact(session, ride.passenger_id)
        if contact is None:
            alert.note = "sem contato cadastrado"
        else:
            text = self._no_signal_text(session, ride.ride_id, ride.passenger_id, where, gap)
            self._notify_contact(contact, text, alert, ride.ride_id)
        session.flush()
        return alert

    # --- SOS ---------------------------------------------------------------------------------------

    def sos(self, session: Session, passenger_id: str, ride_id: str, now: float) -> SosResult:
        ride = repo.get_ride(session, ride_id)
        if ride.passenger_id != passenger_id:
            raise NotYourRide("Essa corrida não é sua.")
        if ride.state not in _ON_THE_MOVE:
            raise InvalidTransition("O SOS vale só durante a corrida.")
        contact = repo.get_emergency_contact(session, passenger_id)
        where = self.positions.get(ride.rider_id) if ride.rider_id else None
        if not self.store.claim(f"{ride_id}:sos", now, SOS_REPEAT_S):
            previous = session.query(SafetyAlertRow).filter_by(ride_id=ride_id, kind="sos").order_by(
                SafetyAlertRow.id.desc()
            ).first()
            if previous is not None:
                notified = previous.note == "contato avisado"
                if contact is not None and not notified:     # o primeiro aviso falhou ou ainda não havia contato
                    notified = self._notify_contact(contact, self._sos_text(session, ride_id, passenger_id, where), previous, ride_id)
                    session.flush()
                return SosResult(previous.id, contact is not None, notified, True)
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
            notified = self._notify_contact(contact, self._sos_text(session, ride_id, passenger_id, where), alert, ride_id)
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

    def _notify_contact(self, contact, text: str, alert, ride_id: str) -> bool:
        """Avisa o contato e anota o resultado no alerta. O WhatsApp fora do ar não pode impedir o alerta."""
        try:
            self.notifier.notify(contact.phone, text)
        except Exception:
            log.exception("falha ao avisar o contato de emergência da corrida %s", ride_id)
            alert.note = "falha ao avisar o contato"
            return False
        alert.note = "contato avisado"
        return True

    @staticmethod
    def _no_signal_text(session: Session, ride_id: str, passenger_id: str, where: GeoPoint | None, gap_s: float) -> str:
        ride = repo.get_ride(session, ride_id)
        passenger = session.get(UserRow, passenger_id)
        card = queries.rider_card(session, ride.rider_id)
        place = (
            f"Última posição: https://maps.google.com/?q={where.lat:.6f},{where.lng:.6f}"
            if where else "A posição da moto não está disponível."
        )
        minutes = max(1, round(gap_s / 60))
        return (
            f"Perdemos o sinal da moto de {passenger.name} há {minutes} minuto(s), no meio da corrida. "
            f"Moto {card.moto_model}, placa {card.plate}, motoqueiro {card.name}. {place}"
        )

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
