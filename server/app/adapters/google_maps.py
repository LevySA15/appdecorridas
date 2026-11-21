"""Rotas do Google (Routes API v2): distância, tempo e traçado das corridas.

O servidor chama o Google uma vez por cotação (`route`) e, raramente, para a moto que está terminando outra
corrida (`eta_seconds`). Qualquer falha — rede, chave ruim, cota, resposta estranha, ponto sem rota — devolve a
estimativa de `FakeMaps` e deixa uma linha no registro: o passageiro nunca fica sem pedir moto por causa de um
serviço de fora. A chave vai só no cabeçalho `X-Goog-Api-Key` e nunca aparece no registro.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import date

from app.adapters.fake_maps import FakeMaps
from app.domain.clock import local_date
from app.domain.geo import GeoPoint
from app.domain.maps import MapsProvider, Route

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELDS_ROUTE = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
_FIELDS_ETA = "routes.duration"

log = logging.getLogger("app.google_maps")

# (endereço, cabeçalhos, corpo JSON, tempo máximo em segundos) -> resposta JSON já lida
Post = Callable[[str, dict[str, str], dict, float], dict]


def decode_polyline(encoded: str) -> tuple[GeoPoint, ...]:
    """O traçado que o Google devolve (algoritmo de polilinha codificada, precisão 1e5)."""
    points: list[GeoPoint] = []
    index = 0
    lat = lng = 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                chunk = ord(encoded[index]) - 63
                index += 1
                result |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append(GeoPoint(lat / 1e5, lng / 1e5))
    return tuple(points)


def urllib_post(url: str, headers: dict[str, str], body: dict, timeout_s: float) -> dict:
    """O chamador de verdade: POST com corpo JSON pela biblioteca padrão (sem dependência nova)."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={**headers, "Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())


class _BadReply(Exception):
    """A resposta do Google não tem o que precisamos."""


class _NoRoute(_BadReply):
    """O Google respondeu direito, mas não existe rota entre os dois pontos (não é falha do serviço)."""


def _first_route(reply: object) -> dict:
    if isinstance(reply, dict) and not reply.get("routes"):
        raise _NoRoute("sem rota entre os pontos")              # `{}` é a resposta dele para "não há rota"
    routes = reply.get("routes") if isinstance(reply, dict) else None
    if not isinstance(routes, list) or not isinstance(routes[0], dict):
        raise _BadReply("resposta fora do formato")
    return routes[0]


def _duration_s(route: dict) -> int:
    text = route.get("duration")
    if not isinstance(text, str) or not text.endswith("s"):
        raise _BadReply("duração ilegível")
    try:
        seconds = float(text[:-1])
    except ValueError:
        raise _BadReply("duração ilegível") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise _BadReply("duração ilegível")
    return int(round(seconds))


def _distance_m(route: dict) -> int:
    meters = route.get("distanceMeters")
    if isinstance(meters, bool) or not isinstance(meters, (int, float)) or not math.isfinite(meters) or meters <= 0:
        raise _BadReply("distância ilegível")
    return int(round(meters))


class GoogleMaps:
    """`MapsProvider` pela Routes API do Google, com a estimativa de `fallback` quando algo dá errado.

    Ordem em cada pedido: cache → pausa → teto do dia → chamada. Só resposta boa do Google entra no cache (a
    estimativa não: quando o Google volta, volta já). O teto e a pausa vivem na memória do processo: protegem o
    gasto e o tempo de espera, não são contabilidade exata (reiniciar o servidor zera o contador).
    """

    def __init__(
        self,
        api_key: str,
        *,
        travel_mode: str = "DRIVE",
        fallback: MapsProvider | None = None,
        post: Post | None = None,
        clock: Callable[[], float] = time.time,
        timeout_s: float = 3.0,
        daily_limit: int = 800,
        route_ttl_s: float = 21_600.0,
        eta_ttl_s: float = 120.0,
        cache_size: int = 2000,
        failures_before_pause: int = 3,
        pause_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self.travel_mode = travel_mode
        self.fallback: MapsProvider = fallback if fallback is not None else FakeMaps()
        self.post: Post = post if post is not None else urllib_post
        self.clock = clock
        self.timeout_s = timeout_s
        self.daily_limit = daily_limit
        self.route_ttl_s = route_ttl_s
        self.eta_ttl_s = eta_ttl_s
        self.cache_size = cache_size
        self.failures_before_pause = failures_before_pause
        self.pause_s = pause_s
        self._lock = threading.Lock()
        self._routes: dict[tuple, tuple[float, Route]] = {}
        self._etas: dict[tuple, tuple[float, int]] = {}
        self._day: date | None = None
        self._calls_today = 0
        self._limit_warned_day: date | None = None
        self._failures_in_a_row = 0
        self._paused_until = 0.0

    # --- o que os serviços usam ---------------------------------------------------------------------

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        key = self._key(origin, destination)
        with self._lock:
            cached = self._lookup(self._routes, key)
            if cached is not None:
                return cached
            if not self._reserve_call():
                return self.fallback.route(origin, destination)
        try:
            route = _first_route(self._call(origin, destination, _FIELDS_ROUTE))
            distance, duration = _distance_m(route), _duration_s(route)
            encoded = (route.get("polyline") or {}).get("encodedPolyline")
            points = decode_polyline(encoded) if isinstance(encoded, str) and encoded else ()
            found = Route(distance, duration, points if len(points) >= 2 else (origin, destination))
        except Exception as exc:
            self._failed(exc)
            return self.fallback.route(origin, destination)
        with self._lock:
            self._failures_in_a_row = 0
            self._store(self._routes, key, found, self.route_ttl_s)
        return found

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        key = self._key(origin, destination)
        with self._lock:
            cached = self._lookup(self._etas, key)
            if cached is not None:
                return cached
            if not self._reserve_call():
                return self.fallback.eta_seconds(origin, destination)
        try:
            seconds = _duration_s(_first_route(self._call(origin, destination, _FIELDS_ETA)))
        except Exception as exc:
            self._failed(exc)
            return self.fallback.eta_seconds(origin, destination)
        with self._lock:
            self._failures_in_a_row = 0
            self._store(self._etas, key, seconds, self.eta_ttl_s)
        return seconds

    # --- peças ---------------------------------------------------------------------------------------

    @staticmethod
    def _key(origin: GeoPoint, destination: GeoPoint) -> tuple[float, float, float, float]:
        # 4 casas decimais ≈ 11 m: pedidos quase iguais dividem a resposta
        return (round(origin.lat, 4), round(origin.lng, 4), round(destination.lat, 4), round(destination.lng, 4))

    def _lookup(self, cache: dict, key: tuple):
        entry = cache.get(key)
        if entry is None:
            return None
        if entry[0] <= self.clock():
            del cache[key]
            return None
        return entry[1]

    def _store(self, cache: dict, key: tuple, value, ttl_s: float) -> None:
        cache.pop(key, None)                       # reinserir move para o fim (o mais antigo é o primeiro)
        cache[key] = (self.clock() + ttl_s, value)
        while len(cache) > self.cache_size:
            del cache[next(iter(cache))]

    def _reserve_call(self) -> bool:
        """Com o `_lock` na mão: diz se pode chamar o Google agora e, se pode, já conta a chamada no teto do dia."""
        now = self.clock()
        if now < self._paused_until:
            return False
        today = local_date(now)
        if today != self._day:
            self._day, self._calls_today = today, 0
        if self._calls_today >= self.daily_limit:
            if self._limit_warned_day != today:
                self._limit_warned_day = today
                log.warning(
                    "Google Maps: teto de %d chamadas por dia atingido; uso a estimativa até amanhã.", self.daily_limit
                )
            return False
        self._calls_today += 1
        return True

    def _failed(self, exc: Exception) -> None:
        reason = str(exc).replace(self._api_key, "***")
        log.warning("Google Maps falhou (%s: %s); usei a estimativa.", type(exc).__name__, reason)
        if isinstance(exc, _NoRoute):
            return                                  # o serviço está bem: só não há rota para esse pedido
        with self._lock:
            self._failures_in_a_row += 1
            if self._failures_in_a_row >= self.failures_before_pause:
                self._failures_in_a_row = 0
                self._paused_until = self.clock() + self.pause_s
                log.warning(
                    "Google Maps: %d falhas seguidas; pausa de %d s (uso a estimativa).",
                    self.failures_before_pause, int(self.pause_s),
                )

    def _call(self, origin: GeoPoint, destination: GeoPoint, fields: str) -> dict:
        def waypoint(point: GeoPoint) -> dict:
            return {"location": {"latLng": {"latitude": point.lat, "longitude": point.lng}}}

        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": fields}
        body = {
            "origin": waypoint(origin), "destination": waypoint(destination), "travelMode": self.travel_mode,
            "routingPreference": "TRAFFIC_UNAWARE", "units": "METRIC",
        }
        return self.post(ROUTES_URL, headers, body, self.timeout_s)
