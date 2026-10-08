import pytest

from app.domain.config import PricingConfig
from app.domain.pricing import (
    distance_fare_cents,
    final_price_cents,
    price_reason,
    smooth_factor,
    target_factor,
)


def test_tarifa_pela_distancia():
    assert distance_fare_cents(0) == 300
    assert distance_fare_cents(2000) == 600
    assert distance_fare_cents(3000) == 750


def test_distancia_negativa_da_erro():
    with pytest.raises(ValueError):
        distance_fare_cents(-1)


def test_fator_alvo_com_muita_moto_livre_cai_para_o_minimo():
    assert target_factor(pending_requests=0, free_riders=10) == 0.8


def test_fator_alvo_com_pouca_moto_sobe_para_o_maximo():
    assert target_factor(pending_requests=5, free_riders=2) == 1.6


def test_fator_alvo_equilibrado_e_um():
    assert target_factor(pending_requests=3, free_riders=3) == 1.0
    assert target_factor(pending_requests=0, free_riders=0) == 1.0


def test_fator_alvo_intermediario():
    assert target_factor(pending_requests=2, free_riders=1) == pytest.approx(1.5)


def test_fator_alvo_com_numero_negativo_da_erro():
    with pytest.raises(ValueError):
        target_factor(-1, 0)
    with pytest.raises(ValueError):
        target_factor(0, -1)


def test_fator_muda_aos_poucos():
    assert smooth_factor(1.0, 1.6) == pytest.approx(1.1)
    assert smooth_factor(1.2, 0.8) == pytest.approx(1.1)


def test_fator_perto_do_alvo_vai_direto():
    assert smooth_factor(1.0, 1.05) == pytest.approx(1.05)


def test_preco_final_tipico():
    assert final_price_cents(2000, 1.0) == 600
    assert final_price_cents(3000, 1.0) == 750


def test_preco_final_com_fator_alto_arredonda_para_50_centavos():
    assert final_price_cents(2000, 1.6) == 950


def test_preco_final_nunca_fica_abaixo_do_piso():
    assert final_price_cents(2000, 0.8) == 500
    assert final_price_cents(0, 0.8) == 500


def test_preco_final_com_fator_fora_da_faixa_e_limitado():
    assert final_price_cents(3000, 5.0) == 1200
    assert final_price_cents(3000, 0.1) == 600


def test_arredondamento_meio_para_cima():
    cfg = PricingConfig(base_fare_cents=500, per_km_cents=0)
    assert final_price_cents(0, 1.25, cfg) == 650


def test_motivo_do_preco():
    assert price_reason(0.8) == "Muita moto livre agora, preço menor."
    assert price_reason(1.0) == "Preço normal para este horário."
    assert price_reason(1.6) == "Poucas motos agora, preço maior."
