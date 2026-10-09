import json

import pytest
from sqlalchemy import text

from app.db.config_store import AppConfig, load_app_config, load_config, save_config
from app.domain.config import (
    DispatchConfig,
    FeeConfig,
    FeeTier,
    PricingConfig,
    RideConfig,
    SafetyConfig,
)


def test_sem_nada_salvo_usa_os_padroes(session):
    assert load_app_config(session) == AppConfig(
        PricingConfig(), FeeConfig(), RideConfig(), DispatchConfig(), SafetyConfig()
    )


def test_salva_e_le_a_configuracao_de_preco(session):
    custom = PricingConfig(base_fare_cents=400, per_km_cents=200, min_price_cents=600)
    save_config(session, "pricing", custom)
    assert load_config(session, "pricing") == custom
    assert load_app_config(session).pricing == custom


def test_salva_e_le_as_faixas_de_taxa(session):
    custom = FeeConfig(tiers=(FeeTier(1, 3, 120), FeeTier(4, None, 100)), cash_debt_limit_cents=2000)
    save_config(session, "fees", custom)
    session.expire_all()
    assert load_config(session, "fees") == custom


def test_salvar_de_novo_substitui_o_valor(session):
    save_config(session, "rides", RideConfig(pix_window_s=90))
    save_config(session, "rides", RideConfig(pix_window_s=150))
    assert load_config(session, "rides").pix_window_s == 150


def test_faixa_abaixo_do_piso_nao_e_salva(session):
    ruim = FeeConfig(tiers=(FeeTier(1, None, 10),))
    with pytest.raises(ValueError, match="piso"):
        save_config(session, "fees", ruim)
    assert load_config(session, "fees") == FeeConfig()


def test_chave_desconhecida_e_tipo_errado_sao_recusados(session):
    with pytest.raises(ValueError, match="desconhecida"):
        save_config(session, "outra", PricingConfig())
    with pytest.raises(ValueError, match="tipo"):
        save_config(session, "pricing", FeeConfig())
    with pytest.raises(ValueError, match="desconhecida"):
        load_config(session, "outra")


def _gravar_cru(session, key: str, valor: dict) -> None:
    session.execute(
        text("INSERT INTO app_config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": json.dumps(valor)},
    )


def test_dados_corrompidos_no_banco_dao_erro_claro(session):
    # Review final do plano 1: configuração ruim não pode virar valor perigoso em silêncio.
    _gravar_cru(session, "fees", {"tiers": [{"from_ride": 1, "to_ride": None, "fee_cents": 10}], "min_fee_cents": 70,
                                  "trial_rides": 10, "entry_fee_cents": 5000, "cash_debt_limit_cents": 1000,
                                  "max_debt_share": 0.5})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "fees")


def test_campo_desconhecido_ou_faltando_no_banco_da_erro_claro(session):
    _gravar_cru(session, "pricing", {"base_fare_cents": 300, "campo_novo": 1})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "pricing")
    _gravar_cru(session, "fees", {"min_fee_cents": 70})
    with pytest.raises(ValueError, match="inválida"):
        load_config(session, "fees")
