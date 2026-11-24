import pytest

from app.domain.geo import GeoPoint, distance_to_route_m, distance_to_segment_m, haversine_m, route_for_app, simplify_route
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


# --- traçado para o app --------------------------------------------------------------------------------------


def _reta(n):
    """n pontos numa linha reta de norte a sul (a cada ~11 m)."""
    return [GeoPoint(-12.9 - i * 0.0001, -39.26) for i in range(n)]


def test_traco_com_dois_pontos_ou_menos_fica_igual():
    assert simplify_route([]) == []
    um = [GeoPoint(-12.9, -39.2)]
    assert simplify_route(um) == um
    dois = [GeoPoint(-12.9, -39.2), GeoPoint(-12.8, -39.1)]
    assert simplify_route(dois) == dois


def test_pontos_no_meio_de_uma_reta_somem_e_as_pontas_ficam():
    reta = _reta(200)
    assert simplify_route(reta) == [reta[0], reta[-1]]


def test_curva_fica_e_o_desenho_nao_foge_da_tolerancia():
    # desce 400 m, vira para leste 400 m (um "L" de rua)
    descida = [GeoPoint(-12.9 - i * 0.0001, -39.26) for i in range(37)]
    leste = [GeoPoint(descida[-1].lat, -39.26 + i * 0.0001) for i in range(1, 38)]
    traco = descida + leste
    simples = simplify_route(traco, tolerance_m=4.0)
    assert simples[0] == traco[0] and simples[-1] == traco[-1]
    assert GeoPoint(descida[-1].lat, -39.26) in simples                 # a esquina ficou
    assert len(simples) < len(traco) / 5
    for p in traco:                                                      # nenhum ponto some se ficar a mais de 4 m da linha nova
        assert distance_to_route_m(p, simples) <= 4.0 + 1e-6


def test_tolerancia_maior_tira_mais_pontos():
    zigue = [GeoPoint(-12.9 - i * 0.0001, -39.26 + (0.00003 if i % 2 else 0)) for i in range(40)]      # zigue-zague de ~3 m
    assert len(simplify_route(zigue, tolerance_m=1.0)) > len(simplify_route(zigue, tolerance_m=10.0))


def test_traco_para_o_app_vira_lista_de_pares_com_5_casas():
    assert route_for_app(((-12.964412345, -39.259712345), (-12.95, -39.25))) == [[-12.96441, -39.25971], [-12.95, -39.25]]
    assert route_for_app(()) == []
    assert route_for_app([[-12.9, -39.2], [-12.8, -39.1]]) == [[-12.9, -39.2], [-12.8, -39.1]]      # o que vem do banco são listas
