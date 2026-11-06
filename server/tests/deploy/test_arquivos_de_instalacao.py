"""Os arquivos de instalação (systemd, Caddy, modelo de configuração) dizem o que o servidor precisa para ir ao ar."""
import re
import subprocess
from pathlib import Path

import pytest

from app.infra.documents import MAX_UPLOAD_BYTES
from app.settings import load_settings, parse_env_file

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _unidade(nome: str) -> dict[str, dict[str, list[str]]]:
    """Lê um arquivo do systemd: {seção: {chave: [valores...]}} (a mesma chave pode repetir)."""
    secoes: dict[str, dict[str, list[str]]] = {}
    atual = ""
    for bruta in (DEPLOY / nome).read_text(encoding="utf-8").splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("["):
            atual = linha.strip("[]")
            secoes[atual] = {}
        else:
            chave, _, valor = linha.partition("=")
            secoes[atual].setdefault(chave.strip(), []).append(valor.strip())
    return secoes


def test_servidor_roda_com_um_processo_so_atras_do_proxy_e_como_usuario_comum():
    servico = _unidade("app-corrida.service")["Service"]
    comando = servico["ExecStart"][0]
    assert "--factory app.main:create_default_app" in comando
    assert "--workers 1" in comando                                   # o hub de WebSocket e o agendador vivem no processo
    assert "--host 127.0.0.1" in comando and "0.0.0.0" not in comando  # só o proxy chega nele
    # explícito (o uvicorn já faz por padrão): o limite de pedidos de código por IP depende de ler o IP verdadeiro
    assert "--proxy-headers" in comando and "--forwarded-allow-ips 127.0.0.1" in comando
    assert servico["User"] == ["corrida"]


def test_servidor_aplica_as_migracoes_ao_subir_e_reinicia_sozinho():
    servico = _unidade("app-corrida.service")
    assert any("alembic upgrade head" in c for c in servico["Service"]["ExecStartPre"])
    assert servico["Service"]["Restart"] == ["on-failure"]
    assert "StartLimitBurst" in servico["Unit"]                       # migração quebrada não fica em laço infinito
    depois = " ".join(servico["Unit"]["After"])
    assert "postgresql.service" in depois and "redis-server.service" in depois
    assert servico["Service"]["EnvironmentFile"] == ["/etc/app-corrida/app.env"]


def test_servidor_so_escreve_na_propria_pasta_de_dados():
    servico = _unidade("app-corrida.service")["Service"]
    assert servico["NoNewPrivileges"] == ["yes"] and servico["ProtectSystem"] == ["strict"]
    assert servico["ReadWritePaths"] == ["/var/lib/app-corrida"]


def test_backup_e_um_servico_de_uma_rodada_com_a_mesma_configuracao():
    servico = _unidade("app-corrida-backup.service")["Service"]
    assert servico["Type"] == ["oneshot"] and servico["User"] == ["corrida"]
    assert servico["EnvironmentFile"] == ["/etc/app-corrida/app.env"]
    assert servico["ExecStart"] == ["/opt/app-corrida/server/deploy/backup.sh"]
    assert servico["ReadWritePaths"] == ["/var/backups/app-corrida"]


def test_backup_roda_todo_dia_e_recupera_o_que_perdeu_com_a_maquina_desligada():
    temporizador = _unidade("app-corrida-backup.timer")
    assert temporizador["Timer"]["OnCalendar"] == ["*-*-* 03:30:00"]
    assert temporizador["Timer"]["Persistent"] == ["true"]
    assert temporizador["Install"]["WantedBy"] == ["timers.target"]


def _caddy() -> str:
    return (DEPLOY / "Caddyfile").read_text(encoding="utf-8")


def test_caddy_faz_https_para_o_dominio_da_configuracao_e_entrega_ao_servidor():
    texto = _caddy()
    assert re.search(r"^\{\$APP_DOMAIN\}\s*\{", texto, re.M)
    assert "reverse_proxy 127.0.0.1:8000" in texto
    assert "Strict-Transport-Security" in texto
    codigo = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("#"))
    assert not re.search(r"\b[a-z0-9-]+\.(com|net|org|app|dev|com\.br)\b", codigo), "domínio de verdade no modelo"


def test_caddy_fecha_as_rotas_de_desenvolvimento_mesmo_se_o_servidor_as_montar():
    texto = _caddy()
    bloqueio = re.search(r"@\w+\s+path\s+(.+)", texto)
    assert bloqueio, "falta o bloqueio das rotas de desenvolvimento"
    for caminho in ("/v1/dev/*", "/docs", "/docs/*", "/openapi.json"):
        assert caminho in bloqueio.group(1).split()
    assert re.search(r"respond\s+@\w+\s+404", texto)


def test_caddy_deixa_passar_uma_foto_de_documento_inteira():
    limite = re.search(r"max_size\s+(\d+)\s*MB", _caddy())
    assert limite, "falta o limite de tamanho do corpo"
    assert int(limite.group(1)) * 1000 * 1000 >= MAX_UPLOAD_BYTES


CHAVES = {"DATABASE_URL", "REDIS_URL", "APP_MODE", "DEV_ROUTES", "WEBHOOK_SECRET", "UPLOAD_DIR", "BACKUP_DIR",
          "BACKUP_KEEP_DAYS", "BACKUP_KEEP_UPLOAD_DAYS"}


def test_modelo_de_configuracao_tem_as_chaves_certas_e_nenhum_segredo_de_verdade():
    valores = parse_env_file(DEPLOY / "app.env.example")
    assert set(valores) == CHAVES
    assert "TROQUE" in valores["DATABASE_URL"] and valores["WEBHOOK_SECRET"].startswith("TROQUE")
    assert valores["APP_MODE"] == "dev" and valores["DEV_ROUTES"] == "off"


def test_modelo_de_configuracao_e_aceito_pelo_servidor_e_nao_e_ignorado_pelo_git():
    config = load_settings(env_path=DEPLOY / "app.env.example", environ={})
    assert config.mode == "dev" and config.dev_routes is False
    assert config.upload_dir == Path("/var/lib/app-corrida/uploads")
    ignorado = subprocess.run(["git", "check-ignore", "-q", str(DEPLOY / "app.env.example")], capture_output=True)
    assert ignorado.returncode == 1, "o modelo precisa ir para o git"


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh"])
def test_scripts_sao_executaveis(script):
    assert (DEPLOY / script).stat().st_mode & 0o111
