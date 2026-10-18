"""Cria (ou reencontra) as pessoas da simulação: entra, cadastra os motoqueiros e o administrador os aprova."""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass

from simulator.people import JPEG, Identity, RiderIdentity, passenger_identity, rider_identity
from simulator.world import Login, SimulationError, TokenCache, World, login

PARALLEL = 8            # quantas pessoas entram ao mesmo tempo


@dataclass
class Population:
    admin: Login
    riders: list[tuple[RiderIdentity, Login]]
    passengers: list[tuple[Identity, Login]]


async def _setup_rider(world: World, cache: TokenCache, admin: Login, identity: RiderIdentity) -> Login:
    api = world.api
    me = await login(api, cache, identity.phone, "rider")
    state = await api.call("GET", "/v1/rider/state", token=me.token)
    status = state.body["registration"]["status"]
    if status == "not_registered":
        keys = {}
        for field, kind in (("selfie_key", "selfie"), ("cnh_photo_key", "cnh"), ("crlv_key", "crlv")):
            sent = await api.call("PUT", "/v1/rider/documents/{kind}", token=me.token, params={"kind": kind}, content=JPEG)
            if not sent.ok:
                raise SimulationError(f"a foto de {identity.name} foi recusada: {sent.message}")
            keys[field] = sent.body["key"]
        registered = await api.call(
            "POST", "/v1/rider/register", token=me.token,
            json={
                "name": identity.name, "cpf": identity.cpf, "cnh_number": identity.cnh_number, "plate": identity.plate,
                "moto_model": identity.moto_model, "cnh_expires_on": identity.cnh_expires_on.isoformat(),
                "crlv_expires_on": identity.crlv_expires_on.isoformat(), **keys,
            },
            ok=("duplicate_registration",),
        )
        if not registered.ok:
            raise SimulationError(f"o cadastro de {identity.name} foi recusado: {registered.message}")
        status = "pending"
    if status == "pending":
        await api.call("POST", "/v1/admin/riders/{rider_id}/approve", token=admin.token, params={"rider_id": me.user_id})
    elif status == "blocked":
        await api.call("POST", "/v1/admin/riders/{rider_id}/unblock", token=admin.token, params={"rider_id": me.user_id})
    elif status != "approved":
        raise SimulationError(f"{identity.name} está com o cadastro em '{status}' e não dá para usar")
    return me


async def _setup_passenger(world: World, cache: TokenCache, identity: Identity) -> Login:
    api = world.api
    me = await login(api, cache, identity.phone, "passenger")
    current = await api.call("GET", "/v1/me", token=me.token)
    if current.ok and current.body["name"] != identity.name:
        await api.call("PUT", "/v1/me", token=me.token, json={"name": identity.name})
    if world.choices("contact", identity.index).chance(world.profile.emergency_contact):
        await api.call(
            "PUT", "/v1/passenger/emergency-contact", token=me.token,
            json={"name": "Contato de emergência", "phone": f"75 98000-{identity.index:04d}"},
        )
    return me


async def prepare(
    world: World, cache: TokenCache, admin_phone: str, riders: int, passengers: int, today: dt.date | None = None
) -> Population:
    today = today or dt.date.today()
    admin = await login(world.api, cache, admin_phone, "admin")
    gate = asyncio.Semaphore(PARALLEL)

    async def limited(coro):
        async with gate:
            return await coro

    rider_ids = [rider_identity(i, today) for i in range(1, riders + 1)]
    passenger_ids = [passenger_identity(i) for i in range(1, passengers + 1)]
    rider_logins = await asyncio.gather(*[limited(_setup_rider(world, cache, admin, i)) for i in rider_ids])
    passenger_logins = await asyncio.gather(*[limited(_setup_passenger(world, cache, i)) for i in passenger_ids])
    return Population(admin, list(zip(rider_ids, rider_logins)), list(zip(passenger_ids, passenger_logins)))
