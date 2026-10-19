"""O passageiro de mentira: vê o preço, pede, paga, acompanha, responde ao aviso de segurança e avalia."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from simulator.feed import Feed
from simulator.geo import City
from simulator.people import Identity
from simulator.stats import RideRecord
from simulator.world import Login, World

END_WAIT_S = 3.0                # quanto esperar pelo aviso final depois que a corrida some do estado


SIM_CPF = "529.982.247-25"       # chave Pix de mentira (CPF de exemplo, com dígitos verificadores certos) dos saques


def _place(place) -> dict:
    return {"lat": place.point[0], "lng": place.point[1], "text": place.text}


class PassengerActor:
    def __init__(self, world: World, identity: Identity, me: Login) -> None:
        self.w = world
        self.p = world.profile
        self.identity = identity
        self.me = me
        self.ch = world.choices("passenger", identity.index)
        self.city = City(self.ch.rng, self.p.city_scale)
        self.feed = Feed(world.ws_url, me.token, world.stats)
        self.state: dict | None = None
        self.current: RideRecord | None = None
        self._generation = 0                    # geração da conexão quando a corrida começou
        self._vanished_at: float | None = None
        self._cancelled_by_me = False
        self._next_request_at = 0.0
        self._last_poll = -1e9
        self._plans: dict[tuple, float | None] = {}
        self._done: set[tuple] = set()
        self._rate_queue: list[tuple[float, str]] = []
        self._requesting = False                # entre reservar a vaga do pedido e a corrida existir

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
        """Sem pedido em andamento, sem corrida e sem QR que ele ainda vai pagar."""
        s = self.state
        if self._requesting or self.current is not None or (s is not None and s["ride"] is not None):
            return False
        if s is not None:
            fee = s.get("pending_fee")
            if fee is not None and not self._decided(("fee", fee["ride_id"])):
                return False                        # ainda vai pagar a taxa pendente
            for fee in s.get("recent_fees") or ():
                if fee["appeal_state"] == "open":
                    return False                    # recurso esperando a decisão do administrador
                if fee["can_appeal"] and not self._decided(("appeal", fee["ride_id"])):
                    return False                    # ainda vai decidir se recorre
        unpaid = s["pending_payment"] if s is not None else None
        if unpaid is None:
            return True
        return self._decided(("qr", unpaid["ride_id"]))

    def _decided(self, key: tuple) -> bool:
        """Já escolheu o que fazer com isto (pagar ou não): o plano existe e é "não" ou já foi feito."""
        return key in self._plans and (self._plans[key] is None or key in self._done)

    async def refresh(self) -> None:
        reply = await self.call("GET", "/v1/passenger/state")
        if reply.ok:
            self.state = reply.body
        self._last_poll = self.w.now()

    # --- laço principal ---------------------------------------------------------------------------

    async def run(self) -> None:
        feed_task = asyncio.create_task(self.feed.run())
        try:
            await self.refresh()
            await self._top_up()
            self._next_request_at = self.w.now() + self.ch.rng.uniform(0, self.p.mean_gap_s) * self.p.pace
            last = self.w.now()
            while not self.w.stopped:
                await self.feed.wait(self.p.tick_s)
                now = self.w.now()
                dt, last = now - last, now
                if self.ch.chance(self.p.drop_feed * dt / 60):
                    self.note("conexão em tempo real derrubada de propósito")
                    await self.feed.drop()
                every = self.p.poll_every_s if self.current is not None else self.p.poll_every_s * 3
                events = self.feed.take()
                if events or self.feed.resync or now - self._last_poll >= every:
                    self.feed.resync = False
                    await self.refresh()
                if await self._act(now):
                    await self.refresh()
        finally:
            await self.feed.stop(feed_task)

    # --- decisões ------------------------------------------------------------------------------------

    async def _act(self, now: float) -> bool:
        s = self.state
        if s is None:
            return False
        ride = s["ride"]
        if ride is not None:
            self._vanished_at = None
            return await self._ride(ride, now)
        if self.current is not None:
            return self._finish(now)
        if s.get("pending_fee") and await self._pay_fee(s["pending_fee"], now):
            return True
        if s["pending_payment"] and await self._pay_unpaid(s["pending_payment"], now):
            return True
        if await self._appeal(s.get("recent_fees") or (), now):
            return True
        if await self._rate(now):
            return True
        if await self._withdraw(s, now):
            return True
        if now >= self._next_request_at and s["blocked_reason"] is None:
            return await self._request(now)
        return False

    async def _request(self, now: float) -> bool:
        if not self.w.reserve_request():
            return False
        self._requesting = True
        try:
            return await self._request_ride(now)
        finally:
            self._requesting = False

    async def _request_ride(self, now: float) -> bool:
        origin, destination = self.city.random_trip()
        quote = await self.call(
            "POST", "/v1/passenger/quotes", json={"pickup": _place(origin), "destination": _place(destination)},
            ok=("not_allowed",),
        )
        if not quote.ok:
            self.w.release_request()
            self._next_request_at = now + self.ch.think(20, 60)
            return False
        self.w.stats.price_reasons[quote.body["reason"]] += 1
        if self.ch.chance(self.p.give_up_price):
            self.note("desistiu do preço")
            self.w.release_request()
            self._next_request_at = now + self.ch.gap_s()
            return False
        allowed = quote.body["payment_methods"]
        if "balance" in allowed and self.p.use_balance > 0 and self.ch.chance(self.p.use_balance):
            method = "balance"
        else:
            method = self.ch.method([m for m in allowed if m != "balance"])
        body = {"quote_id": quote.body["quote_id"], "method": method}

        async def asked():
            return await self.call("POST", "/v1/passenger/rides", json=body, ok=("quote_expired", "not_allowed"))

        if self.ch.chance(self.p.double_request):
            self.note("toque duplo em pedir")
            replies = await asyncio.gather(asked(), asked())
        else:
            replies = [await asked()]
        created = next((r for r in replies if r.ok), None)
        if created is None:
            self.w.release_request()
            self._next_request_at = now + self.ch.think(10, 30)
            return False
        ride = created.body
        self.current = RideRecord(
            ride["ride_id"], self.identity.index, method, ride["price_cents"], ride["price_reason"], now,
        )
        if method == "balance":
            self.w.stats.fees["pagas_com_saldo"] += 1
        self.w.stats.rides[ride["ride_id"]] = self.current
        self._generation = self.feed.generation
        self._cancelled_by_me = False
        return True

    async def _ride(self, ride: dict, now: float) -> bool:
        record = self.current
        if record is None:                              # corrida que já existia quando a simulação começou
            return False
        ride_id, state = ride["ride_id"], ride["state"]
        if ride["queued"]:
            record.queued = True
        if state == "searching":
            self._when(
                ("cancel-search", ride_id),
                lambda: now + self.ch.think(10, 40) if self.ch.chance(self.p.cancel_while_searching) else None,
            )
            return await self._cancel_if_due(("cancel-search", ride_id), now)
        if state in ("accepted", "queued", "arrived"):
            if record.accepted_at is None:
                record.accepted_at = now
            if state == "arrived" and record.arrived_at is None:
                record.arrived_at = now
            if await self._pay_pix(ride, record, now):
                return True
            if state == "arrived":
                at = self._when(("say-pin", ride_id), lambda: now + self.ch.think(2, 8))
                if now >= at and ride_id not in self.w.pins:
                    self.w.pins[ride_id] = ride["pin"]
                return False
            self._when(
                ("cancel-accepted", ride_id),
                lambda: now + self.ch.think(*self.p.cancel_accept_s) if self.ch.chance(self.p.cancel_after_accept) else None,
            )
            return await self._cancel_if_due(("cancel-accepted", ride_id), now)
        if state == "in_progress":
            if record.started_at is None:
                record.started_at = now
            return await self._safety(ride, now)
        return False

    async def _pay_pix(self, ride: dict, record: RideRecord, now: float) -> bool:
        """Paga o Pix do pedido, a qualquer hora enquanto ele vale: com a moto a caminho ou já na porta."""
        ride_id = ride["ride_id"]
        if ride["pay"] is None or ("pay", ride_id) in self._done:
            return False
        at = self._when(
            ("pay", ride_id),
            lambda: now + (self.p.pix_window_s + 8 if self.ch.chance(self.p.pay_pix_late) else self.ch.think(3, 40)),
        )
        if now < at:
            return False
        self._done.add(("pay", ride_id))
        if now - record.accepted_at > self.p.pix_window_s:
            self.note("Pix pago depois do prazo")
        await self.w.pay_pix(ride["pay"]["charge_id"])
        return True

    async def _cancel_if_due(self, key: tuple, now: float) -> bool:
        at = self._plans.get(key)
        if at is None or now < at or key in self._done:
            return False
        self._done.add(key)
        ride_id = key[1]
        reply = await self.call(
            "POST", "/v1/passenger/rides/{ride_id}/cancel", params={"ride_id": ride_id}, ok=("invalid_state",)
        )
        if reply.ok:
            self._cancelled_by_me = True
            self.note("passageiro cancelou")
        return True

    async def _safety(self, ride: dict, now: float) -> bool:
        ride_id = ride["ride_id"]
        params = {"ride_id": ride_id}
        alert = ride["safety_alert"]
        if alert is not None:
            key = ("alert", alert["alert_id"])
            at = self._when(key, lambda: now + self.ch.think(5, 40))
            if now < at or key in self._done:
                return False
            self._done.add(key)
            if self.ch.chance(self.p.sos_on_check):
                return await self._sos(ride_id)
            if self.ch.chance(self.p.ok_to_check):
                await self.call(
                    "POST", "/v1/rides/{ride_id}/safety/{alert_id}/ok",
                    params={**params, "alert_id": alert["alert_id"]}, ok=("alert_closed",),
                )
                self.note("respondeu \"está tudo bem\"")
                return True
            self.note("ignorou o aviso de segurança")
            return False
        at = self._when(
            ("sos", ride_id), lambda: now + self._into_the_trip(ride) if self.ch.chance(self.p.spontaneous_sos) else None
        )
        if at is not None and now >= at and ("sos", ride_id) not in self._done:
            self._done.add(("sos", ride_id))
            return await self._sos(ride_id)
        return False

    def _into_the_trip(self, ride: dict) -> float:
        """Um momento qualquer no meio da corrida, calculado pelo tempo que ela deve durar."""
        expected = ride["distance_m"] / (self.p.speed_mps * self.p.speedup)
        return expected * self.ch.rng.uniform(0.2, 0.7)

    async def _sos(self, ride_id: str) -> bool:
        reply = await self.call("POST", "/v1/rides/{ride_id}/sos", params={"ride_id": ride_id}, ok=("invalid_state",))
        if reply.ok:
            self.note("SOS apertado")
        return True

    def _finish(self, now: float) -> bool:
        """A corrida saiu do estado: descobre como terminou pelos avisos (o estado só diz que acabou)."""
        record = self.current
        assert record is not None
        if self._vanished_at is None:
            self._vanished_at = now
        seen = self.feed.seen.get(record.ride_id, set())
        reconnected = self.feed.generation != self._generation
        if self._cancelled_by_me:
            outcome = "cancelled"
        elif "trip_completed" in seen:
            outcome = "completed"
        elif "no_rider" in seen:
            outcome = "no_rider"
        elif "ride_cancelled" in seen:
            data = self.feed.latest.get((record.ride_id, "ride_cancelled"), {})
            outcome = data.get("reason") or "cancelled"
        elif now - self._vanished_at < END_WAIT_S:
            return False                                        # o aviso pode estar a caminho
        else:
            outcome = "completed" if record.started_at is not None else "unknown"
            if not reconnected:
                record.missing_events.append("aviso final")
        fee = self.feed.latest.get((record.ride_id, "cancel_fee"))
        if fee:                                                 # taxa de cancelamento tardio (o passageiro cancelou ou não apareceu)
            fees = self.w.stats.fees
            fees["cobradas"] += 1
            fees["centavos"] += fee["fee_cents"]
            fees["do_saldo"] += fee["from_balance_cents"]
            fees["retidas"] += fee["retained_cents"]
            fees["pendentes"] += 1 if fee["pending_cents"] else 0
        record.outcome = outcome
        record.ended_at = now
        if not reconnected:
            expected = []
            if record.accepted_at is not None:
                expected.append("rider_accepted")
            if outcome == "completed":
                expected.append("trip_completed")
            record.missing_events += [kind for kind in expected if kind not in seen]
        if outcome == "completed" and self.ch.chance(self.p.rate):
            self._rate_queue.append((now + self.ch.think(2, 20), record.ride_id))
        self.current = None
        self._next_request_at = now + self.ch.gap_s()
        return False

    async def _pay_unpaid(self, pending: dict, now: float) -> bool:
        key = pending["ride_id"]
        if pending["blocked"] and ("blocked", key) not in self._done:
            self._done.add(("blocked", key))
            self.note("passageiro bloqueado por falta de pagamento")
            self._plans[("qr", key)] = now + self.ch.think(20, 90) if self.ch.chance(0.9) else None
        at = self._when(
            ("qr", key), lambda: now + self.ch.think(15, 90) if self.ch.chance(self.p.pay_qr) else None
        )
        if at is None or now < at or ("qr", key) in self._done or not pending["charge_id"]:
            return False
        self._done.add(("qr", key))
        await self.w.pay_pix(pending["charge_id"])
        self.note("QR do fim da corrida pago")
        return True

    async def _top_up(self) -> None:
        """Ao começar, às vezes recarrega o saldo (só se o servidor deixa; o de desenvolvimento deixa desligado)."""
        if not (self.state and self.state.get("topup_enabled")):
            return
        own = self.w.choices("topup", self.identity.index)      # sorteio à parte: não muda o resto do que a pessoa faz
        if not own.chance(self.p.topup):
            return
        amount = own.rng.choice([1000, 1500, 2000])
        reply = await self.call("POST", "/v1/passenger/balance/topup", json={"amount_cents": amount}, ok=("topup_disabled",))
        if reply.ok:
            await self.w.pay_pix(reply.body["charge_id"])
            self.w.stats.fees["recargas"] += 1
            self.note("saldo recarregado")

    async def _withdraw(self, s: dict, now: float) -> bool:
        """Às vezes saca parte do saldo por Pix (só se o servidor deixa e o saldo passa do mínimo)."""
        balance = s.get("balance_cents", 0)
        if not (s.get("withdraw_enabled") and self.p.withdraw > 0 and balance >= s.get("withdraw_min_cents", 500)):
            return False
        key = ("withdraw", balance)
        at = self._when(key, lambda: now + self.ch.think(10, 60) if self.ch.chance(self.p.withdraw) else None)
        if at is None or now < at or key in self._done:
            return False
        self._done.add(key)
        amount = min(balance, s["withdraw_max_cents"], self.ch.rng.choice([500, 1000, balance]))
        amount = min(balance, max(amount, s["withdraw_min_cents"]))
        reply = await self.call(
            "POST", "/v1/passenger/balance/withdraw", json={"amount_cents": amount, "pix_key": SIM_CPF},
            ok=("withdraw_disabled", "not_allowed"),
        )
        if reply.ok:
            self.w.stats.fees["saques"] += 1
            self.w.stats.fees["saques_centavos"] += amount
            self.note("saldo sacado")
        return True

    async def _pay_fee(self, fee: dict, now: float) -> bool:
        """Paga a taxa de cancelamento pendente (com o saldo ou pelo Pix) ou escolhe ficar bloqueado."""
        key = ("fee", fee["ride_id"])
        at = self._when(key, lambda: now + self.ch.think(15, 90) if self.ch.chance(self.p.pay_fee) else None)
        if at is None:
            if ("fee-skip", fee["ride_id"]) not in self._done:
                self._done.add(("fee-skip", fee["ride_id"]))
                self.note("taxa pendente não paga (por escolha)")
            return False
        if now < at or key in self._done:
            return False
        self._done.add(key)
        reply = await self.call("POST", "/v1/passenger/fees/pay", ok=("nothing_to_pay",))
        if not reply.ok:
            return True
        if not reply.body["paid"]:
            await self.w.pay_pix(reply.body["charge_id"])
        self.w.stats.fees["pagas_depois"] += 1
        self.note("taxa de cancelamento paga")
        return True

    async def _appeal(self, fees, now: float) -> bool:
        """Às vezes pede revisão de uma taxa recente."""
        for fee in fees:
            key = ("appeal", fee["ride_id"])
            if not fee["can_appeal"]:
                continue
            at = self._when(key, lambda: now + self.ch.think(20, 120) if self.ch.chance(self.p.appeal_fee) else None)
            if at is None or now < at or key in self._done:
                continue
            self._done.add(key)
            reply = await self.call(
                "POST", "/v1/passenger/rides/{ride_id}/fee/appeal", params={"ride_id": fee["ride_id"]},
                json={"text": "Cancelei porque a moto estava demorando (simulação)."}, ok=("appeal_not_allowed",),
            )
            if reply.ok:
                self.w.stats.fees["recursos_pedidos"] += 1
                self.note("recurso da taxa pedido")
                return True
        return False

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
