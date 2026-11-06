"""O guia de instalação (docs/instalacao.md) combina com os arquivos que ele manda copiar."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
GUIA = RAIZ / "docs" / "instalacao.md"


def _texto() -> str:
    return GUIA.read_text(encoding="utf-8")


def test_guia_comeca_dizendo_que_e_teste_fechado():
    inicio = "\n".join(_texto().splitlines()[:25]).lower()
    assert "fechado" in inicio and "dinheiro de verdade" in inicio


def test_todo_arquivo_de_implantacao_citado_existe():
    citados = set(re.findall(r"server/deploy/[A-Za-z0-9_.\-]+", _texto()))
    assert {"server/deploy/Caddyfile", "server/deploy/app.env.example", "server/deploy/restore.sh",
            "server/deploy/app-corrida.service", "server/deploy/app-corrida-backup.timer"} <= citados
    faltam = sorted(c for c in citados if not (RAIZ / c).exists())
    assert not faltam, f"o guia cita arquivos que não existem: {faltam}"


def test_guia_cobre_o_que_o_levy_vai_precisar():
    texto = _texto()
    for termo in ("API_URL", "DEV_ROUTES", "journalctl", "restore.sh", "ensaio", "ufw", "create-admin", "/health",
                  "--substituir", "Antes de abrir para o público"):
        assert termo in texto, f"o guia não fala de {termo!r}"


def test_comandos_do_guia_usam_os_nomes_certos_do_servico():
    texto = _texto()
    assert "systemctl enable --now app-corrida" in texto and "app-corrida-backup.timer" in texto
    assert "TROQUE" in texto                                       # explica o que trocar no modelo
    assert "ssh -L" in texto                                       # túnel para as rotas de desenvolvimento


def test_readme_do_servidor_aponta_para_o_guia():
    readme = (RAIZ / "server" / "README.md").read_text(encoding="utf-8")
    assert "docs/instalacao.md" in readme and "deploy/" in readme
