import random

import pytest

from simulator.geo import CITY_CENTER, City, distance_m, midpoint, move_toward, offset, sideways_point


def test_offset_anda_a_distancia_pedida():
    ponto = offset(CITY_CENTER, 300, 400)
    assert distance_m(CITY_CENTER, ponto) == pytest.approx(500, abs=2)


def test_move_toward_anda_ate_o_alvo_e_para_la():
    alvo = offset(CITY_CENTER, 0, 100)
    meio = move_toward(CITY_CENTER, alvo, 40)
    assert distance_m(CITY_CENTER, meio) == pytest.approx(40, abs=0.5)
    assert move_toward(CITY_CENTER, alvo, 500) == alvo
    assert move_toward(alvo, alvo, 10) == alvo


def test_viagens_sorteadas_respeitam_o_minimo_e_o_maximo():
    cidade = City(random.Random(3))
    for _ in range(200):
        origem, destino = cidade.random_trip()
        assert 300 <= distance_m(origem.point, destino.point) <= 3500


def test_cidade_pequena_para_os_testes_mantem_viagens_acima_do_minimo_do_servidor():
    cidade = City(random.Random(5), scale=0.2)
    for _ in range(100):
        origem, destino = cidade.random_trip()
        assert 150 <= distance_m(origem.point, destino.point) <= 800


def test_mesmo_sorteio_mesma_cidade():
    a, b = City(random.Random(9)), City(random.Random(9))
    assert [a.random_trip() for _ in range(5)] == [b.random_trip() for _ in range(5)]


def test_o_texto_do_lugar_tem_zona_e_numero():
    lugar = City(random.Random(1)).random_place()
    assert lugar.text.endswith(f" - {lugar.zone}") and any(c.isdigit() for c in lugar.text)


def test_desvio_fica_para_o_lado_do_trecho_e_nao_em_cima_dele():
    a, b = CITY_CENTER, offset(CITY_CENTER, 1000, 0)                    # trecho de 1 km para o norte
    desvio = sideways_point(a, b, 700)
    assert distance_m(desvio, midpoint(a, b)) == pytest.approx(700, abs=3)
    assert abs(desvio[0] - midpoint(a, b)[0]) < 1e-6                    # mesma altura: saiu para o lado, não para a frente
