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
