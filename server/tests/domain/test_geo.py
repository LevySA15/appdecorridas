import pytest

from app.domain.geo import GeoPoint, distance_to_route_m, distance_to_segment_m, haversine_m
from tests.helpers import ORIGIN, pt


def test_haversine_um_grau_de_latitude():
    assert haversine_m(GeoPoint(0, 0), GeoPoint(1, 0)) == pytest.approx(111_195, abs=50)


def test_haversine_mesmo_ponto_e_zero():
    assert haversine_m(ORIGIN, ORIGIN) == 0


def test_distancia_ao_segmento_perpendicular():
    a, b = pt(0, -1000), pt(0, 1000)
    assert distance_to_segment_m(pt(111, 0), a, b) == pytest.approx(111, abs=2)


def test_distancia_ao_segmento_alem_da_ponta():
    a, b = pt(0, -1000), pt(0, 1000)
    assert distance_to_segment_m(pt(0, 1500), a, b) == pytest.approx(500, abs=5)


def test_distancia_a_rota_usa_o_trecho_mais_proximo():
    route = [pt(0, 0), pt(0, 1000), pt(1000, 1000)]
    assert distance_to_route_m(pt(500, 1050), route) == pytest.approx(50, abs=3)


def test_rota_vazia_da_erro():
    with pytest.raises(ValueError):
        distance_to_route_m(ORIGIN, [])


def test_rota_de_um_ponto_usa_distancia_direta():
    assert distance_to_route_m(pt(0, 300), [ORIGIN]) == pytest.approx(300, abs=3)
