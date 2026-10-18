"""O motoqueiro de mentira: fica disponível, manda a posição, responde às ofertas e faz a corrida inteira pela API."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from simulator.feed import Feed
from simulator.geo import City, Point, distance_m, midpoint, move_toward, sideways_point
from simulator.people import RiderIdentity
from simulator.world import Login, World

ARRIVED_M = 25.0                # a que distância do ponto a moto considera que chegou
GO_ONLINE_ERRORS = ("entry_pending", "not_approved", "blocked", "documents_expired")


def _point(place: dict) -> Point:
    return (place["lat"], place["lng"])


class RiderActor:
    def __init__(self, world: World, identity: RiderIdentity, me: Login, start: Point) -> None:
        self.w = world
        self.p = world.profile
        self.identity = identity
        self.me = me
        self.ch = world.choices("rider", identity.index)
        self.city = City(self.ch.rng, self.p.city_scale)
        self.feed = Feed(world.ws_url, me.token, world.stats)
        self.pos = start
        self.speed = self.ch.rider_speed()
        self.state: dict | None = None
        self.ride_distance_m = 0.0              # quanto andou com corrida (o fim da rodada usa para saber se há progresso)
        self._route: list[Point] = []
        self._route_key: tuple | None = None
        self._route_speed = self.speed
        self._pause_until = 0.0
        self._break_until = 0.0
        self._stop_point: Point | None = None
        self._plans: dict[tuple, float | None] = {}
        self._done: set[tuple] = set()
        self._offers: dict[str, list] = {}
        self._late: list[tuple[float, str]] = []          # respostas a ofertas que já venceram
        self._rate_queue: list[tuple[float, str]] = []
        self._last_poll = -1e9

    # --- ajudas ---------------------------------------------------------------------------------

    def note(self, text: str) -> None:
        self.w.stats.note(text)

    async def call(self, method: str, template: str, **kwargs):
        return await self.w.api.call(method, template, token=self.me.token, **kwargs)

    def _when(self, key: tuple, make: Callable[[], float | None]) -> float | None:
        if key not in self._plans:
            self._plans[key] = make()
        return self._plans[key]

    @property
    def idle(self) -> bool:
        """Sem corrida, sem oferta, sem corrida na fila e sem dinheiro que ele ainda vai confirmar."""
        s = self.state
        if s is None:
            return True
        if s["ride"] or s["offer"] or s["queued_ride"] or self._late:
            return False
        unpaid = s["awaiting_payment"]
        if unpaid is None:
            return True
        key = ("cash", unpaid["ride_id"])
        return key in self._plans and (self._plans[key] is None or key in self._done)

    async def refresh(self) -> None:
        reply = await self.call("GET", "/v1/rider/state")
        if reply.ok:
            self.state = reply.body
        self._last_poll = self.w.now()

    async def report_position(self) -> None:
        await self.call("POST", "/v1/rider/position", json={"lat": self.pos[0], "lng": self.pos[1]})

    # --- laço principal ---------------------------------------------------------------------------

    async def run(self) -> None:
        feed_task = asyncio.create_task(self.feed.run())
        try:
            await self.report_position()
            await self.refresh()
            last = last_report = self.w.now()
            while not self.w.stopped:
                await self.feed.wait(self.p.tick_s)
                now = self.w.now()
                dt, last = now - last, now
                if self.ch.chance(self.p.drop_feed * dt / 60):
                    self.note("conexão em tempo real derrubada de propósito")
                    await self.feed.drop()
                self._plan_route(now)
                self._move(dt, now)
                if self._reports_position() and now - last_report >= self.p.position_every_s:
                    last_report = now
                    await self.report_position()
                events = self.feed.take()
                if events or self.feed.resync or now - self._last_poll >= self.p.poll_every_s:
                    self.feed.resync = False
                    await self.refresh()
                if await self._act(now):
                    await self.refresh()
        finally:
            await self.feed.stop(feed_task)

    def _reports_position(self) -> bool:
        s = self.state
        return s is not None and (s["registration"]["online"] or s["ride"] is not None)

    # --- movimento ---------------------------------------------------------------------------------

    def _plan_route(self, now: float) -> None:
        s = self.state
        if s is None:
            return
        ride = s["ride"]
        if ride is None:
            if self._route_key is not None and self._route_key[0] != "wander":
                self._route, self._route_key = [], None
            return
        key = (ride["ride_id"], ride["state"])
        if key == self._route_key:
            return
        self._route_key = key
        self._route_speed = self.speed
        self._stop_point = None
        if ride["state"] == "accepted":
            self._route = [_point(ride["pickup"])]
        elif ride["state"] == "in_progress":
            pickup, destination = _point(ride["pickup"]), _point(ride["destination"])
            self._route = [destination]
            if self.ch.chance(self.p.detour):
                self._route = [sideways_point(pickup, destination, self.p.detour_m), destination]
                self.note("desvio de rota")
            self._stop_point = midpoint(pickup, destination) if self.ch.chance(self.p.stop_mid_trip) else None
        else:
            self._route = []

    def _move(self, dt: float, now: float) -> None:
        if now < self._pause_until or not self._route:
            return
        target = self._route[0]
        before = self.pos
        self.pos = move_toward(self.pos, target, self._route_speed * dt)
        if self.state is not None and self.state["ride"] is not None:
            self.ride_distance_m += distance_m(before, self.pos)
        if self._stop_point is not None and distance_m(self.pos, self._stop_point) < 40:
            self._stop_point = None
            self._pause_until = now + self.p.stop_s
            self.note("parada longa no meio da corrida")
        if self.pos == target:
            self._route.pop(0)
            if not self._route and self._route_key is not None and self._route_key[0] == "wander":
                self._pause_until = now + self.ch.think(5, 40)
                self._route_key = None

    def _wander(self, now: float) -> None:
        if self._route or now < self._pause_until or now < self._break_until:
            return
        self._route = [self.city.random_place().point]
        self._route_key = ("wander",)
        self._route_speed = self.speed * 0.6

    # --- decisões ------------------------------------------------------------------------------------

    async def _act(self, now: float) -> bool:
        """Faz no máximo uma coisa por volta e devolve se mudou algo no servidor (aí o estado é relido)."""
        s = self.state
        if s is None:
            return False
        reg = s["registration"]
        if not reg["online"] and reg["status"] == "approved" and s["ride"] is None and now >= self._break_until:
            return await self._go_online(now)
        if self._late and now >= self._late[0][0]:
            _, ride_id = self._late.pop(0)
            self.note("oferta respondida tarde")
            await self.call("POST", "/v1/rider/offers/{ride_id}/accept", params={"ride_id": ride_id}, ok=("offer_gone",))
            return True
        if s["offer"] and await self._offer(s["offer"], now):
            return True
        if s["ride"] and await self._ride(s["ride"], now):
            return True
        if s["awaiting_payment"] and await self._cash(s["awaiting_payment"], now):
            return True
        if await self._rate(now):
            return True
        if reg["online"] and s["ride"] is None:
            self._wander(now)
        return False

    async def _go_online(self, now: float) -> bool:
        reply = await self.call("POST", "/v1/rider/online", ok=GO_ONLINE_ERRORS)
        if reply.code == "entry_pending":
            await self._pay_entry()
            reply = await self.call("POST", "/v1/rider/online", ok=GO_ONLINE_ERRORS)
        if not reply.ok:
            self.note(f"não conseguiu ficar disponível ({reply.code})")
            self._break_until = now + 30.0
        return reply.ok

    async def _pay_entry(self) -> None:
        charge = await self.call("POST", "/v1/rider/entry-charge")
        if charge.ok:
            await self.w.pay_pix(charge.body["charge_id"])
            self.note("entrada de R$ 50 paga")

    async def _offer(self, offer: dict, now: float) -> bool:
        ride_id = offer["ride_id"]
        if ride_id not in self._offers:
            action = self.ch.offer_action()
            if action == "ignore":
                self.note("oferta ignorada")
            elif action == "late":
                self._late.append((now + self.p.offer_window_s + 1.5, ride_id))      # só responde depois de vencer
            delay = min(self.ch.think(1, 6), self.p.offer_window_s * 0.6)
            self._offers[ride_id] = [now + delay, action if action in ("accept", "decline") else "none", False]
        at, action, done = self._offers[ride_id]
        if done or now < at or action == "none":
            return False
        self._offers[ride_id][2] = True
        params = {"ride_id": ride_id}
        if action == "decline":
            await self.call("POST", "/v1/rider/offers/{ride_id}/decline", params=params, ok=("offer_gone",))
            self.note("oferta recusada")
            return True
        tap = "/v1/rider/offers/{ride_id}/accept"
        if self.ch.chance(self.p.double_tap):
            self.note("toque duplo em aceitar")
            await asyncio.gather(
                self.call("POST", tap, params=params, ok=("offer_gone",)),
                self.call("POST", tap, params=params, ok=("offer_gone",)),
            )
        else:
            await self.call("POST", tap, params=params, ok=("offer_gone",))
        self.note("oferta aceita")
        return True

    async def _ride(self, ride: dict, now: float) -> bool:
        ride_id, state = ride["ride_id"], ride["state"]
        params = {"ride_id": ride_id}
        base = "/v1/rider/rides/{ride_id}"
        if state == "accepted":
            if distance_m(self.pos, _point(ride["pickup"])) > ARRIVED_M:
                return False
            await self.call("POST", base + "/arrive", params=params, ok=("invalid_state",))
            return True
        if state == "arrived":
            if not ride["helmet_confirmed"]:
                at = self._when(("helmet", ride_id), lambda: now + self.ch.think(3, 10))
                if now < at:
                    return False
                await self.call("POST", base + "/helmet", params=params, ok=("invalid_state",))
                return True
            pin = self.w.pins.get(ride_id)
            if pin is None or (ride["method"] == "pix" and not ride["pix_paid"]):
                return False                    # sem o código, ou esperando o Pix cair (o app não deixa sair antes)
            if ("wrong-pin", ride_id) not in self._done and self.ch.chance(self.p.wrong_pin):
                self._done.add(("wrong-pin", ride_id))
                self.note("código errado digitado")
                wrong = "0000" if pin != "0000" else "1111"
                await self.call("POST", base + "/start", params=params, json={"pin": wrong}, ok=("wrong_pin", "invalid_state"))
                return True
            await self.call("POST", base + "/start", params=params, json={"pin": pin}, ok=("invalid_state",))
            return True
        if state == "in_progress":
            if self._route or distance_m(self.pos, _point(ride["destination"])) > ARRIVED_M:
                return False
            reply = await self.call("POST", base + "/complete", params=params, ok=("invalid_state",))
            if reply.ok:
                await self._after_ride(ride_id, now)
            return True
        return False

    async def _after_ride(self, ride_id: str, now: float) -> None:
        if self.ch.chance(self.p.rate):
            self._rate_queue.append((now + self.ch.think(2, 15), ride_id))
        if self.ch.chance(self.p.take_break):
            await self.call("POST", "/v1/rider/offline", ok=("invalid_state",))
            self._break_until = self.w.now() + self.ch.think(60, 180)
            self.note("pausa do motoqueiro")

    async def _cash(self, ride: dict, now: float) -> bool:
        ride_id = ride["ride_id"]
        at = self._when(
            ("cash", ride_id), lambda: now + self.ch.think(5, 40) if self.ch.chance(self.p.cash_by_hand) else None
        )
        if at is None or now < at or ("cash", ride_id) in self._done:
            return False
        self._done.add(("cash", ride_id))
        await self.call("POST", "/v1/rider/rides/{ride_id}/cash-received", params={"ride_id": ride_id}, ok=("invalid_state",))
        self.note("dinheiro confirmado na mão")
        return True

    async def _rate(self, now: float) -> bool:
        for index, (at, ride_id) in enumerate(self._rate_queue):
            if now >= at:
                del self._rate_queue[index]
                await self.call(
                    "POST", "/v1/rides/{ride_id}/rating", params={"ride_id": ride_id}, json={"stars": self.ch.stars()},
                    ok=("already_rated",),
                )
                return True
        return False
