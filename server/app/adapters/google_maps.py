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
import time
import urllib.request
from collections.abc import Callable

from app.adapters.fake_maps import FakeMaps
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


def _first_route(reply: object) -> dict:
    routes = reply.get("routes") if isinstance(reply, dict) else None
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
        raise _BadReply("sem rota")
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
    """`MapsProvider` pela Routes API do Google, com a estimativa de `fallback` quando algo dá errado."""

    def __init__(
        self,
        api_key: str,
        *,
        travel_mode: str = "DRIVE",
        fallback: MapsProvider | None = None,
        post: Post | None = None,
        clock: Callable[[], float] = time.time,
        timeout_s: float = 3.0,
    ) -> None:
        self._api_key = api_key
        self.travel_mode = travel_mode
        self.fallback: MapsProvider = fallback if fallback is not None else FakeMaps()
        self.post: Post = post if post is not None else urllib_post
        self.clock = clock
        self.timeout_s = timeout_s

    def route(self, origin: GeoPoint, destination: GeoPoint) -> Route:
        try:
            route = _first_route(self._call(origin, destination, _FIELDS_ROUTE))
            distance, duration = _distance_m(route), _duration_s(route)
            encoded = (route.get("polyline") or {}).get("encodedPolyline")
            points = decode_polyline(encoded) if isinstance(encoded, str) and encoded else ()
            return Route(distance, duration, points if len(points) >= 2 else (origin, destination))
        except Exception as exc:
            self._warn(exc)
            return self.fallback.route(origin, destination)

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        try:
            return _duration_s(_first_route(self._call(origin, destination, _FIELDS_ETA)))
        except Exception as exc:
            self._warn(exc)
            return self.fallback.eta_seconds(origin, destination)

    def _call(self, origin: GeoPoint, destination: GeoPoint, fields: str) -> dict:
        def waypoint(point: GeoPoint) -> dict:
            return {"location": {"latLng": {"latitude": point.lat, "longitude": point.lng}}}

        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": fields}
        body = {
            "origin": waypoint(origin), "destination": waypoint(destination), "travelMode": self.travel_mode,
            "routingPreference": "TRAFFIC_UNAWARE", "units": "METRIC",
        }
        return self.post(ROUTES_URL, headers, body, self.timeout_s)

    def _warn(self, exc: Exception) -> None:
        reason = str(exc).replace(self._api_key, "***")
        log.warning("Google Maps falhou (%s: %s); usei a estimativa.", type(exc).__name__, reason)
