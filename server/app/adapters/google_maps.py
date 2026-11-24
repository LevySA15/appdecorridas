"""Rotas e endereços do Google: distância, tempo e traçado das corridas (Routes API v2) e o endereço escrito de um ponto
(Geocoding API).

O servidor chama o Google uma vez por cotação (`route`) e, raramente, para a moto que está terminando outra
corrida (`eta_seconds`). Qualquer falha — rede, chave ruim, cota, resposta estranha, ponto sem rota — devolve a
estimativa de `FakeMaps` e deixa uma linha no registro: o passageiro nunca fica sem pedir moto por causa de um
serviço de fora. A chave das rotas vai só no cabeçalho `X-Goog-Api-Key`; a do endereço (a API antiga do Google só
aceita na URL) nunca aparece no registro.

O endereço escrito (`describe`) tem teto de chamadas por dia e pausa depois de falhas **próprios**: um problema nele
(API de endereços desligada na chave, cota) não para as rotas, e o contrário também não.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.parse
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
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# só endereços de rua, bairro e lugar (sem "plus codes" e sem cidade/estado inteiros)
_GEOCODE_RESULT_TYPES = "street_address|route|premise|subpremise|neighborhood|sublocality"

log = logging.getLogger("app.google_maps")

# (endereço, cabeçalhos, corpo JSON, tempo máximo em segundos) -> resposta JSON já lida
Post = Callable[[str, dict[str, str], dict, float], dict]
# (endereço completo com a chave na URL, tempo máximo em segundos) -> resposta JSON já lida
Get = Callable[[str, float], dict]


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


def urllib_get(url: str, timeout_s: float) -> dict:
    """O chamador de verdade do endereço: GET pela biblioteca padrão."""
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        return json.loads(response.read())


def _component(result: dict, *types: str) -> str | None:
    for wanted in types:
        for part in result.get("address_components") or ():
            if isinstance(part, dict) and wanted in (part.get("types") or ()):
                name = part.get("long_name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return None


def address_text(reply: object) -> str | None:
    """A frase curta do endereço ("Rua Severo Vieira, 120 - São Cristóvão") a partir da resposta da Geocoding API.

    `None` quando o Google não achou endereço ali (`ZERO_RESULTS`: o serviço está bem). Estatus de erro levantam
    `_BadReply` (conta como falha do serviço)."""
    if not isinstance(reply, dict):
        raise _BadReply("resposta fora do formato")
    status = reply.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise _BadReply(f"status {status}")
    results = [r for r in reply.get("results") or () if isinstance(r, dict)]
    for result in results:
        street = _component(result, "route")
        if street is None:
            continue
        number = _component(result, "street_number")
        area = _component(result, "sublocality_level_1", "sublocality", "neighborhood")
        text = f"{street}, {number}" if number else street
        if area and area != street:
            text = f"{text} - {area}"
        return text[:200]
    for result in results:                                     # sem rua (bairro, lugar): as duas primeiras partes
        formatted = result.get("formatted_address")
        if isinstance(formatted, str) and formatted.strip():
            parts = [p.strip() for p in formatted.split(",") if p.strip()]
            return " - ".join(parts[:2])[:200] or None
    return None


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


class _Guard:
    """Teto de chamadas por dia (dia da Bahia) e pausa depois de falhas seguidas, para um tipo de chamada ao Google.

    Vive na memória do processo: protege o gasto e o tempo de espera, não é contabilidade exata (reiniciar o servidor
    zera o contador). Quem usa já está com o `_lock` de `GoogleMaps` na mão."""

    def __init__(self, what: str, fallback: str, limit: int, failures_before_pause: int, pause_s: float) -> None:
        self.what = what
        self.fallback = fallback
        self.limit = limit
        self.failures_before_pause = failures_before_pause
        self.pause_s = pause_s
        self.day: date | None = None
        self.calls_today = 0
        self.limit_warned_day: date | None = None
        self.failures_in_a_row = 0
        self.paused_until = 0.0

    def reserve(self, now: float) -> bool:
        """Diz se pode chamar o Google agora e, se pode, já conta a chamada no teto do dia."""
        if now < self.paused_until:
            return False
        today = local_date(now)
        if today != self.day:
            self.day, self.calls_today = today, 0
        if self.calls_today >= self.limit:
            if self.limit_warned_day != today:
                self.limit_warned_day = today
                log.warning(
                    "Google Maps: teto de %d chamadas por dia (%s) atingido; %s até amanhã.",
                    self.limit, self.what, self.fallback,
                )
            return False
        self.calls_today += 1
        return True

    def succeeded(self) -> None:
        self.failures_in_a_row = 0

    def failed(self, now: float) -> None:
        self.failures_in_a_row += 1
        if self.failures_in_a_row >= self.failures_before_pause:
            self.failures_in_a_row = 0
            self.paused_until = now + self.pause_s
            log.warning(
                "Google Maps: %d falhas seguidas (%s); pausa de %d s (%s).",
                self.failures_before_pause, self.what, int(self.pause_s), self.fallback,
            )


class GoogleMaps:
    """`MapsProvider` pelo Google, com a estimativa de `fallback` quando algo dá errado.

    Ordem em cada pedido: cache → pausa → teto do dia → chamada. Só resposta boa do Google entra no cache (a
    estimativa não: quando o Google volta, volta já). O teto e a pausa vivem na memória do processo: protegem o
    gasto e o tempo de espera, não são contabilidade exata (reiniciar o servidor zera o contador)."""

    def __init__(
        self,
        api_key: str,
        *,
        travel_mode: str = "DRIVE",
        fallback: MapsProvider | None = None,
        post: Post | None = None,
        get: Get | None = None,
        clock: Callable[[], float] = time.time,
        timeout_s: float = 3.0,
        daily_limit: int = 800,
        geocode_daily_limit: int = 600,
        route_ttl_s: float = 21_600.0,
        eta_ttl_s: float = 120.0,
        address_ttl_s: float = 86_400.0,
        cache_size: int = 2000,
        failures_before_pause: int = 3,
        pause_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self.travel_mode = travel_mode
        self.fallback: MapsProvider = fallback if fallback is not None else FakeMaps()
        self.post: Post = post if post is not None else urllib_post
        self.get: Get = get if get is not None else urllib_get
        self.clock = clock
        self.timeout_s = timeout_s
        self.daily_limit = daily_limit
        self.geocode_daily_limit = geocode_daily_limit
        self.route_ttl_s = route_ttl_s
        self.eta_ttl_s = eta_ttl_s
        self.address_ttl_s = address_ttl_s
        self.cache_size = cache_size
        self.failures_before_pause = failures_before_pause
        self.pause_s = pause_s
        self._lock = threading.Lock()
        self._routes: dict[tuple, tuple[float, Route]] = {}
        self._etas: dict[tuple, tuple[float, int]] = {}
        self._addresses: dict[tuple, tuple[float, str | None]] = {}
        self._route_guard = _Guard("rotas", "uso a estimativa", daily_limit, failures_before_pause, pause_s)
        self._address_guard = _Guard(
            "endereços", "sigo sem endereço", geocode_daily_limit, failures_before_pause, pause_s
        )

    # --- o que os serviços usam ---------------------------------------------------------------------

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        key = self._key(origin, destination)
        with self._lock:
            cached = self._lookup(self._routes, key)
            if cached is not None:
                return cached
            if not self._route_guard.reserve(self.clock()):
                return self.fallback.route(origin, destination)
        try:
            route = _first_route(self._call(origin, destination, _FIELDS_ROUTE))
            distance, duration = _distance_m(route), _duration_s(route)
            encoded = (route.get("polyline") or {}).get("encodedPolyline")
            points = decode_polyline(encoded) if isinstance(encoded, str) and encoded else ()
            found = Route(distance, duration, points if len(points) >= 2 else (origin, destination))
        except Exception as exc:
            self._failed(exc, self._route_guard)
            return self.fallback.route(origin, destination)
        with self._lock:
            self._route_guard.succeeded()
            self._store(self._routes, key, found, self.route_ttl_s)
        return found

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        key = self._key(origin, destination)
        with self._lock:
            cached = self._lookup(self._etas, key)
            if cached is not None:
                return cached
            if not self._route_guard.reserve(self.clock()):
                return self.fallback.eta_seconds(origin, destination)
        try:
            seconds = _duration_s(_first_route(self._call(origin, destination, _FIELDS_ETA)))
        except Exception as exc:
            self._failed(exc, self._route_guard)
            return self.fallback.eta_seconds(origin, destination)
        with self._lock:
            self._route_guard.succeeded()
            self._store(self._etas, key, seconds, self.eta_ttl_s)
        return seconds

    def describe(self, point: GeoPoint) -> str | None:
        """O endereço escrito do ponto, ou `None` (sem endereço ali, teto do dia, pausa ou falha: o pedido segue sem texto)."""
        key = (round(point.lat, 5), round(point.lng, 5))     # 5 casas ≈ 1 m: pontos vizinhos não herdam o número da casa
        with self._lock:
            entry = self._addresses.get(key)
            if entry is not None:
                if entry[0] > self.clock():
                    return entry[1]
                del self._addresses[key]
            if not self._address_guard.reserve(self.clock()):
                return None
        query = urllib.parse.urlencode(
            {
                "latlng": f"{point.lat:.6f},{point.lng:.6f}", "language": "pt-BR",
                "result_type": _GEOCODE_RESULT_TYPES, "key": self._api_key,
            }
        )
        try:
            text = address_text(self.get(f"{GEOCODE_URL}?{query}", self.timeout_s))
        except Exception as exc:
            self._failed(exc, self._address_guard)
            return None
        with self._lock:
            self._address_guard.succeeded()
            self._store(self._addresses, key, text, self.address_ttl_s)
        return text

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

    def _failed(self, exc: Exception, guard: _Guard) -> None:
        reason = str(exc).replace(self._api_key, "***").replace(urllib.parse.quote(self._api_key, safe=""), "***")
        log.warning("Google Maps falhou (%s: %s); %s.", type(exc).__name__, reason, guard.fallback)
        if isinstance(exc, _NoRoute):
            return                                  # o serviço está bem: só não há rota para esse pedido
        with self._lock:
            guard.failed(self.clock())

    def _call(self, origin: GeoPoint, destination: GeoPoint, fields: str) -> dict:
        def waypoint(point: GeoPoint) -> dict:
            return {"location": {"latLng": {"latitude": point.lat, "longitude": point.lng}}}

        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": fields}
        body = {
            "origin": waypoint(origin), "destination": waypoint(destination), "travelMode": self.travel_mode,
            "routingPreference": "TRAFFIC_UNAWARE", "units": "METRIC",
        }
        return self.post(ROUTES_URL, headers, body, self.timeout_s)
