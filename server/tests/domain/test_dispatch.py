import threading

from app.adapters.fake_maps import StraightLineEta
from app.domain.config import DispatchConfig
from app.domain.dispatch import (
    Candidate,
    ReservationBook,
    RiderStatus,
    is_eligible,
    is_finishing,
    next_offer,
    rank_candidates,
)
from tests.helpers import ORIGIN, pt

ETA = StraightLineEta(speed_mps=8.0)
CFG = DispatchConfig()


class CountingEta:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def eta_seconds(self, origin, destination):
        self.calls += 1
        return self.inner.eta_seconds(origin, destination)


def free(rider_id: str, north_m: float) -> RiderStatus:
    return RiderStatus(rider_id, pt(north_m, 0))


def test_ordena_pelo_tempo_e_calcula_rota_so_dos_3_mais_proximos():
    riders = [free("r4", 800), free("r2", 400), free("r1", 200), free("r3", 600)]
    eta = CountingEta(ETA)
    result = rank_candidates(riders, ORIGIN, eta, CFG)
    assert [c.rider_id for c in result] == ["r1", "r2", "r3"]
    assert eta.calls == 3
    assert result[0] == Candidate("r1", ETA.eta_seconds(pt(200, 0), ORIGIN), False)


def test_moto_offline_nao_entra():
    riders = [RiderStatus("off", pt(100, 0), online=False), free("r1", 300)]
    assert [c.rider_id for c in rank_candidates(riders, ORIGIN, ETA, CFG)] == ["r1"]


def test_moto_em_corrida_longe_do_fim_nao_entra():
    busy = RiderStatus(
        "busy", pt(200, 0), active_ride_id="x", seconds_to_finish=600, finish_point=pt(5000, 0)
    )
    assert is_finishing(busy, CFG) is False
    assert is_eligible(busy, CFG) is False
    assert rank_candidates([busy], ORIGIN, ETA, CFG) == []


def test_moto_terminando_entra_na_fila_com_tempo_somado():
    finishing = RiderStatus(
        "fin", pt(100, 0), active_ride_id="x", seconds_to_finish=60, finish_point=pt(300, 0)
    )
    assert is_finishing(finishing, CFG) is True
    result = rank_candidates([finishing], ORIGIN, ETA, CFG)
    assert result == [Candidate("fin", 60 + ETA.eta_seconds(pt(300, 0), ORIGIN), True)]


def test_moto_perto_do_destino_conta_como_terminando_mesmo_sem_tempo():
    near_end = RiderStatus(
        "near", pt(4800, 0), active_ride_id="x", seconds_to_finish=None, finish_point=pt(5000, 0)
    )
    assert is_finishing(near_end, CFG) is True


def test_moto_que_ja_tem_corrida_na_fila_nao_entra():
    queued = RiderStatus(
        "q", pt(100, 0), active_ride_id="x", queued_ride_id="y", seconds_to_finish=30, finish_point=pt(200, 0)
    )
    assert is_eligible(queued, CFG) is False


def test_moto_terminando_longe_do_passageiro_perde_para_moto_livre():
    finishing = RiderStatus(
        "fin", pt(100, 0), active_ride_id="x", seconds_to_finish=100, finish_point=pt(100, 0)
    )
    result = rank_candidates([finishing, free("livre", 400)], ORIGIN, ETA, CFG)
    assert [c.rider_id for c in result] == ["livre", "fin"]


def test_proxima_oferta_pula_quem_recusou():
    candidates = [Candidate("a", 10, False), Candidate("b", 20, False), Candidate("c", 30, False)]
    assert next_offer(candidates, set()).rider_id == "a"
    assert next_offer(candidates, {"a"}).rider_id == "b"
    assert next_offer(candidates, {"a", "b", "c"}) is None


def test_reserva_e_idempotente_para_a_mesma_corrida_e_recusa_outra():
    book = ReservationBook()
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-2")  # corrida errada: não libera
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-1")
    assert book.reserve("rider-1", "ride-2") is True


def test_reserva_com_pedidos_ao_mesmo_tempo_so_um_ganha():
    book = ReservationBook()
    results: list[bool] = []
    lock = threading.Lock()

    def tentar(ride_id: str) -> None:
        ok = book.reserve("rider-1", ride_id)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=tentar, args=(f"ride-{i}",)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 1
