"""O dono de mentira: recebe os avisos dos administradores e confere os alertas de segurança que as pessoas geram."""
from __future__ import annotations

import asyncio

from simulator.feed import Feed
from simulator.world import Login, World


class AdminActor:
    def __init__(self, world: World, me: Login) -> None:
        self.w = world
        self.me = me
        self.feed = Feed(world.ws_url, me.token, world.stats)
        self._last = -1e9

    async def run(self) -> None:
        feed_task = asyncio.create_task(self.feed.run())
        try:
            every = max(2.0, 15.0 * self.w.profile.pace)
            while not self.w.stopped:
                await asyncio.sleep(min(every, 1.0))
                self.feed.take()                   # os avisos já foram contados; ninguém precisa guardá-los
                now = self.w.now()
                if now - self._last < every:
                    continue
                self._last = now
                for status in ("sos", "ok"):
                    alerts = await self.w.api.call(
                        "GET", "/v1/admin/safety-alerts", token=self.me.token, query={"status": status, "limit": 50}
                    )
                    for alert in alerts.body if alerts.ok else []:
                        reply = await self.w.api.call(
                            "POST", "/v1/admin/safety-alerts/{alert_id}/resolve", token=self.me.token,
                            params={"alert_id": alert["alert_id"]}, json={"note": "Conferido pelo simulador."},
                            ok=("alert_closed",),
                        )
                        if reply.ok:
                            self.w.stats.note(f"alerta de segurança resolvido pelo administrador ({status})")
        finally:
            await self.feed.stop(feed_task)
