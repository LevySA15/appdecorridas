import pytest

from app.settings import Settings, load_settings, parse_env_file


def test_le_o_arquivo_env_e_ajusta_o_driver(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comentário\n\nDATABASE_URL=postgresql://u:p@localhost:5432/db\nREDIS_URL=redis://localhost:6379/0\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env, environ={})
    assert settings == Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
    )


def test_variavel_de_ambiente_vence_o_arquivo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n", encoding="utf-8")
    settings = load_settings(env_path=env, environ={"REDIS_URL": "redis://b/1"})
    assert settings.redis_url == "redis://b/1"
    assert settings.database_url == "postgresql+psycopg://a@h/x"


def test_falta_de_configuracao_da_erro_claro(tmp_path):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        load_settings(env_path=tmp_path / "nao-existe", environ={})


def test_aspas_no_valor_sao_removidas(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="com aspas"\nB=\'simples\'\nC=sem\n', encoding="utf-8")
    assert parse_env_file(env) == {"A": "com aspas", "B": "simples", "C": "sem"}


def test_url_que_ja_tem_driver_nao_e_alterada(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql+psycopg://u@h/d\nREDIS_URL=redis://h/0\n", encoding="utf-8")
    assert load_settings(env_path=env, environ={}).database_url == "postgresql+psycopg://u@h/d"


def test_configuracoes_da_api_tem_padrao_seguro(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n", encoding="utf-8")
    settings = load_settings(env_path=env, environ={})
    assert settings.mode == "production"          # sem APP_MODE=dev não liga os adaptadores falsos
    assert settings.webhook_secret is None
    assert settings.upload_dir.name == "uploads" and settings.upload_dir.parent.name == "var"


def test_le_modo_segredo_do_webhook_e_pasta_de_documentos(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n"
        "APP_MODE=dev\nWEBHOOK_SECRET=segredo\nUPLOAD_DIR=/dados/docs\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env, environ={})
    assert (settings.mode, settings.webhook_secret) == ("dev", "segredo")
    assert str(settings.upload_dir) == "/dados/docs"


def test_rotas_de_desenvolvimento_ficam_ligadas_por_padrao(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n", encoding="utf-8")
    assert load_settings(env_path=env, environ={}).dev_routes is True


@pytest.mark.parametrize("valor,esperado", [("off", False), ("NAO", False), ("0", False), ("false", False),
                                            ("on", True), ("Sim", True), ("1", True), ("true", True)])
def test_dev_routes_aceita_ligar_e_desligar(tmp_path, valor, esperado):
    env = tmp_path / ".env"
    env.write_text(f"DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\nDEV_ROUTES={valor}\n", encoding="utf-8")
    assert load_settings(env_path=env, environ={}).dev_routes is esperado


def test_dev_routes_com_valor_estranho_da_erro_claro(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\nDEV_ROUTES=talvez\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DEV_ROUTES"):
        load_settings(env_path=env, environ={})


def _env(tmp_path, extra=""):
    arquivo = tmp_path / ".env"
    arquivo.write_text("DATABASE_URL=postgresql://a@h/x\nREDIS_URL=redis://a/0\n" + extra, encoding="utf-8")
    return arquivo


def test_mapa_do_google_tem_padrao_seguro(tmp_path):
    settings = load_settings(env_path=_env(tmp_path), environ={})
    assert settings.google_maps_api_key is None          # sem chave, o mapa continua sendo a estimativa
    assert settings.maps_daily_call_limit == 800
    assert settings.maps_travel_mode == "DRIVE"


def test_le_a_chave_o_teto_e_o_modo_do_mapa(tmp_path):
    extra = "GOOGLE_MAPS_API_KEY=abc\nMAPS_DAILY_CALL_LIMIT=300\nMAPS_TRAVEL_MODE=two_wheeler\n"
    settings = load_settings(env_path=_env(tmp_path, extra), environ={})
    assert (settings.google_maps_api_key, settings.maps_daily_call_limit, settings.maps_travel_mode) == (
        "abc", 300, "TWO_WHEELER",
    )


@pytest.mark.parametrize("teto", ["0", "-5", "abc", "1.5"])
def test_teto_de_chamadas_torto_da_erro_claro(tmp_path, teto):
    with pytest.raises(RuntimeError, match="MAPS_DAILY_CALL_LIMIT"):
        load_settings(env_path=_env(tmp_path), environ={"MAPS_DAILY_CALL_LIMIT": teto})


def test_teto_de_enderecos_tem_padrao_e_le_do_ambiente(tmp_path):
    assert load_settings(env_path=_env(tmp_path), environ={}).geocode_daily_call_limit == 600
    settings = load_settings(env_path=_env(tmp_path), environ={"GEOCODE_DAILY_CALL_LIMIT": "250"})
    assert settings.geocode_daily_call_limit == 250


@pytest.mark.parametrize("teto", ["0", "-5", "abc", "1.5"])
def test_teto_de_enderecos_torto_da_erro_claro(tmp_path, teto):
    with pytest.raises(RuntimeError, match="GEOCODE_DAILY_CALL_LIMIT"):
        load_settings(env_path=_env(tmp_path), environ={"GEOCODE_DAILY_CALL_LIMIT": teto})


def test_modo_de_viagem_invalido_da_erro_claro(tmp_path):
    with pytest.raises(RuntimeError, match="MAPS_TRAVEL_MODE"):
        load_settings(env_path=_env(tmp_path), environ={"MAPS_TRAVEL_MODE": "BICYCLE"})


def test_chave_so_com_espacos_vale_como_sem_chave(tmp_path):
    settings = load_settings(env_path=_env(tmp_path), environ={"GOOGLE_MAPS_API_KEY": "   "})
    assert settings.google_maps_api_key is None
    assert load_settings(env_path=_env(tmp_path), environ={"GOOGLE_MAPS_API_KEY": " k1 "}).google_maps_api_key == "k1"
