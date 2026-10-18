import datetime as dt

import pytest

from simulator.behavior import Profile
from simulator.geo import CITY_CENTER, offset
from simulator.people import rider_identity
from simulator.rider import RiderActor
from simulator.runner import StallWatch, progress_signature
from simulator.stats import RideRecord, Stats
from simulator.world import Login, World


class Moto:
    """Só o que o marcador de progresso olha numa moto."""

    def __init__(self, metros: float) -> None:
        self.ride_distance_m = metros


def moto_de_verdade() -> RiderActor:
    mundo = World(None, Stats(), Profile(), "ws://x/v1/ws", 1)
    return RiderActor(
        mundo, rider_identity(1, dt.date(2026, 10, 18)), Login("u", "t", "+5575982000001", "rider"), CITY_CENTER
    )


def test_assinatura_muda_com_cada_marco_da_corrida_e_com_moto_andando_na_corrida():
    stats = Stats()
    stats.rides["r"] = RideRecord("r", 1, "pix", 700, "x", 0.0)
    antes = progress_signature(stats, [Moto(0)])
    stats.rides["r"].accepted_at = 5.0
    com_marco = progress_signature(stats, [Moto(0)])
    andando = progress_signature(stats, [Moto(120.4)])
    assert len({antes, com_marco, andando}) == 3
    assert progress_signature(stats, [Moto(0)]) == com_marco


def test_nada_novo_por_mais_que_o_limite_e_emperrado():
    vigia = StallWatch(limit_s=100, now=0.0, signature=(0, 0))
    assert not vigia.stalled(50, (0, 0))
    assert not vigia.stalled(99, (0, 0))
    assert vigia.stalled(101, (0, 0))


def test_qualquer_avanco_zera_a_contagem():
    vigia = StallWatch(limit_s=100, now=0.0, signature=(0, 0))
    assert not vigia.stalled(90, (1, 0))          # um marco novo
    assert not vigia.stalled(180, (1, 0))         # 90 s desde o marco
    assert not vigia.stalled(185, (1, 7))         # a moto andou na corrida
    assert vigia.stalled(290, (1, 7))


def test_moto_so_conta_distancia_quando_esta_numa_corrida():
    ator = moto_de_verdade()
    ator._route, ator._route_speed = [offset(CITY_CENTER, 0, 1000)], 10.0
    ator.state = {"ride": None}                   # passeando, sem corrida
    ator._move(1.0, 5.0)
    assert ator.ride_distance_m == 0
    ator.state = {"ride": {"ride_id": "r"}}
    ator._move(1.0, 6.0)
    assert ator.ride_distance_m == pytest.approx(10, abs=0.2)
