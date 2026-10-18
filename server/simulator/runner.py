"""A rodada inteira: prepara as pessoas, solta os atores, espera o tempo passar, deixa as corridas abertas terminarem e confere o servidor."""
from __future__ import annotations

import asyncio
import random

from simulator.admin import AdminActor
from simulator.api import Api
from simulator.geo import City
from simulator.model import Outcome, SimConfig
from simulator.passenger import PassengerActor
from simulator.population import prepare
from simulator.rider import RiderActor
from simulator.stats import Stats
from simulator.world import TokenCache, World


def progress_signature(stats: Stats, riders) -> tuple[int, int]:
    """Muda quando a rodada anda: um marco novo numa corrida (aceita, chegou, saiu, terminou) ou uma moto andando
    com passageiro. Uma moto passeando sem corrida não conta."""
    milestones = sum(
        sum(value is not None for value in (r.accepted_at, r.arrived_at, r.started_at, r.ended_at))
        for r in stats.rides.values()
    )
    return milestones, int(sum(rider.ride_distance_m for rider in riders))


class StallWatch:
    """Diz que a rodada emperrou quando a assinatura de progresso não muda por mais de `limit_s`."""

    def __init__(self, limit_s: float, now: float, signature: tuple) -> None:
        self.limit_s = limit_s
        self._signature = signature
        self._since = now

    def stalled(self, now: float, signature: tuple) -> bool:
        if signature != self._signature:
            self._signature, self._since = signature, now
            return False
        return now - self._since > self.limit_s


async def _guard(stats: Stats, name: str, work) -> None:
    """Um ator que cai por erro do próprio simulador não derruba os outros, mas fica anotado como problema."""
    try:
        await work
    except Exception as exc:  # noqa: BLE001
        stats.flag(f"{name} parou por erro do simulador: {exc!r}")


def _status_line(elapsed: float, riders: list[RiderActor], stats: Stats) -> str:
    online = sum(1 for r in riders if r.state and r.state["registration"]["online"])
    rides = list(stats.rides.values())
    done = sum(1 for r in rides if r.outcome == "completed")
    ended = sum(1 for r in rides if r.outcome is not None)
    return (
        f"[{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}] motos disponíveis {online}/{len(riders)} · corridas: "
        f"{len(rides)} pedidas, {done} concluídas, {len(rides) - ended} em andamento · "
        f"respostas inesperadas: {stats.unexpected_total}"
    )


async def simulate(cfg: SimConfig) -> Outcome:
    cfg.profile.check()
    stats = Stats()
    api = Api(cfg.url, stats)
    ws_url = cfg.url.replace("http", "ws", 1) + "/v1/ws"
    world = World(api, stats, cfg.profile, ws_url, cfg.seed, requests_left=cfg.max_rides)
    cache = TokenCache(cfg.state_dir / "pessoas.json" if cfg.state_dir else None, cfg.url)
    say = cfg.on_status or (lambda _text: None)
    try:
        try:
            people = await prepare(world, cache, cfg.admin_phone, cfg.riders, cfg.passengers)
        finally:
            cache.save()                  # os tokens de quem já entrou valem mesmo se outro cadastro falhou
        say(f"{len(people.riders)} motoqueiros e {len(people.passengers)} passageiros prontos; começando.")
        start_rng = random.Random(f"{cfg.seed}-start")
        city = City(start_rng, cfg.profile.city_scale)
        riders = [RiderActor(world, ident, me, city.random_place().point) for ident, me in people.riders]
        passengers = [PassengerActor(world, ident, me) for ident, me in people.passengers]
        admin = AdminActor(world, people.admin)
        tasks = [
            asyncio.create_task(_guard(stats, f"motoqueiro {r.identity.index}", r.run())) for r in riders
        ] + [
            asyncio.create_task(_guard(stats, f"passageiro {p.identity.index}", p.run())) for p in passengers
        ] + [asyncio.create_task(_guard(stats, "administrador", admin.run()))]
        began = world.now()
        deadline = began + cfg.minutes * 60
        last_status = began
        peak = 0

        def everyone_free() -> bool:
            return all(a.idle for a in riders) and all(a.idle for a in passengers)

        async def tick() -> None:
            nonlocal last_status, peak
            await asyncio.sleep(0.5)
            now = world.now()
            peak = max(peak, sum(1 for r in riders if r.state and r.state["registration"]["online"]))
            if now - last_status >= cfg.status_every_s:
                last_status = now
                say(_status_line(now - began, riders, stats))

        while world.now() < deadline:
            await tick()
            if cfg.max_rides is not None and world.requests_left == 0 and everyone_free():
                break
        world.accepting = False
        say("hora de parar: sem pedidos novos, esperando as corridas abertas terminarem.")
        drain_until = world.now() + cfg.drain_s
        stall_s = cfg.profile.stop_s + 120.0         # mesmo uma parada longa de propósito passa antes disso
        watch = StallWatch(stall_s, world.now(), progress_signature(stats, riders))
        while world.now() < drain_until and not everyone_free():
            await tick()
            if watch.stalled(world.now(), progress_signature(stats, riders)):
                say(f"nada avançou nos últimos {int(stall_s)} s (nenhum marco de corrida, nenhuma moto andando com passageiro): desisto de esperar.")
                break
        await asyncio.sleep(1.0)
        world.stopped = True
        await asyncio.gather(*tasks)
        audit = (await api.call("GET", "/v1/dev/audit")).body or {}
        return Outcome(cfg, stats, audit, world.now() - began, peak)
    finally:
        world.stopped = True
        await api.close()
