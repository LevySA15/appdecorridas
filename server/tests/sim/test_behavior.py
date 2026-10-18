import random
from collections import Counter

import pytest

from simulator.behavior import Choices, Profile, preset


def test_perfis_prontos_existem_e_o_calmo_nao_faz_bagunca():
    calmo, normal, bagunca = preset("calmo"), preset("normal"), preset("bagunca")
    assert calmo.wrong_pin == calmo.stop_mid_trip == calmo.detour == calmo.double_tap == 0
    assert calmo.accept + calmo.decline == 1.0                                # ninguém ignora oferta
    assert normal.stop_mid_trip < bagunca.stop_mid_trip and normal.wrong_pin < bagunca.wrong_pin
    assert (calmo.name, normal.name, bagunca.name) == ("calmo", "normal", "bagunca")
    with pytest.raises(ValueError, match="perfil"):
        preset("inexistente")


def test_oferta_sorteia_as_quatro_respostas_na_proporcao_do_perfil():
    perfil = Profile(accept=0.5, decline=0.2, late=0.1)               # o resto (0.2) ignora
    escolhas = Choices(random.Random(1), perfil)
    contagem = Counter(escolhas.offer_action() for _ in range(4000))
    assert set(contagem) == {"accept", "decline", "late", "ignore"}
    assert contagem["accept"] / 4000 == pytest.approx(0.5, abs=0.04)
    assert contagem["ignore"] / 4000 == pytest.approx(0.2, abs=0.04)


def test_ritmo_encolhe_as_esperas_das_pessoas():
    lento = Choices(random.Random(2), Profile(pace=1.0))
    rapido = Choices(random.Random(2), Profile(pace=0.1))
    assert rapido.think(10, 20) == pytest.approx(lento.think(10, 20) * 0.1)
    assert rapido.gap_s() == pytest.approx(lento.gap_s() * 0.1)


def test_forma_de_pagar_respeita_o_que_o_servidor_oferece():
    escolhas = Choices(random.Random(3), Profile(pix_share=1.0))
    assert escolhas.method(["pix", "cash"]) == "pix"
    assert escolhas.method(["cash"]) == "cash"                         # Pix fora do ar: só dinheiro
    assert Choices(random.Random(3), Profile(pix_share=0.0)).method(["pix", "cash"]) == "cash"


def test_notas_sao_de_1_a_5_e_as_boas_vencem():
    escolhas = Choices(random.Random(4), Profile())
    notas = [escolhas.stars() for _ in range(2000)]
    assert set(notas) <= {1, 2, 3, 4, 5} and notas.count(5) > notas.count(1) * 5


def test_velocidade_da_moto_varia_em_volta_da_base_e_o_aceleramento_multiplica():
    base = [Choices(random.Random(i), Profile(speed_mps=8.0)).rider_speed() for i in range(50)]
    assert all(6.3 <= v <= 9.7 for v in base) and len(set(base)) > 10
    rapido = Choices(random.Random(0), Profile(speed_mps=8.0, speedup=3.0)).rider_speed()
    assert rapido == pytest.approx(Choices(random.Random(0), Profile(speed_mps=8.0)).rider_speed() * 3)


def test_aceleramento_acima_do_limite_do_servidor_e_recusado():
    with pytest.raises(ValueError, match="velocidade"):
        Profile(speed_mps=8.0, speedup=5.0).check()
    Profile(speed_mps=8.0, speedup=4.0).check()


def test_chances_de_resposta_a_oferta_nao_podem_passar_de_cem_por_cento():
    with pytest.raises(ValueError, match="100%"):
        Profile(accept=0.8, decline=0.2, late=0.1).check()
    for nome in ("calmo", "normal", "bagunca"):
        preset(nome).check()
