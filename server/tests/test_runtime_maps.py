"""Escolha do mapa pelo `.env`: sem chave a estimativa de sempre; com chave, as rotas do Google."""
import logging

from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import GoogleMaps
from app.runtime import build_maps
from app.settings import Settings

BASE = {"database_url": "x", "redis_url": "y"}


def test_sem_chave_o_mapa_e_a_estimativa(caplog):
    caplog.set_level(logging.INFO, logger="app.runtime")
    assert isinstance(build_maps(Settings(**BASE)), FakeMaps)
    assert "GOOGLE_MAPS_API_KEY" in caplog.text


def test_com_chave_o_mapa_e_o_do_google_com_teto_e_modo_da_configuracao(caplog):
    caplog.set_level(logging.INFO, logger="app.runtime")
    settings = Settings(
        **BASE, google_maps_api_key="CHAVE-SECRETA-123", maps_daily_call_limit=5, maps_travel_mode="TWO_WHEELER"
    )
    mapa = build_maps(settings)
    assert isinstance(mapa, GoogleMaps)
    assert (mapa.daily_limit, mapa.travel_mode) == (5, "TWO_WHEELER")
    assert "rotas do Google" in caplog.text and "CHAVE-SECRETA-123" not in caplog.text
