import pytest

from app.domain.config import RideConfig, SafetyConfig
from app.domain.rides import Ride, RideState, WrongPin, accept, confirm_helmet, mark_arrived, start_ride, start_search
from app.domain.types import PaymentMethod


def test_limites_novos_tem_padrao():
    assert (RideConfig().min_trip_m, RideConfig().max_trip_m) == (100, 40_000)
    assert (SafetyConfig().alert_cooldown_s, SafetyConfig().max_samples) == (600, 120)


def test_tabela_provisoria_do_sem_sinal_tem_o_padrao_do_levy():
    cfg = SafetyConfig()
    assert (cfg.no_signal_short_m, cfg.no_signal_long_m) == (3000, 10_000)
    assert (cfg.no_signal_short_s, cfg.no_signal_mid_s, cfg.no_signal_long_s) == (120, 240, 360)


def test_codigo_errado_e_um_erro_proprio_mas_continua_sendo_value_error():
    ride = Ride("ride-1", "p1", 700, PaymentMethod.CASH, pin="4821")
    start_search(ride, 0)
    accept(ride, "r1", 1, rider_busy=False)
    mark_arrived(ride, 2)
    confirm_helmet(ride)
    with pytest.raises(WrongPin) as erro:
        start_ride(ride, "0000")
    assert isinstance(erro.value, ValueError)
    assert ride.state is RideState.ARRIVED
