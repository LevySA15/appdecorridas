"""O site do painel: servido sem login, sem dado nenhum, e coerente com a API que ele chama."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAINEL = Path(__file__).resolve().parents[2] / "painel"
JS = PAINEL / "painel.js"


def test_painel_e_servido_sem_login_e_nao_traz_dado_nenhum(client):
    for url in ("/painel", "/painel/"):
        resposta = client.get(url, follow_redirects=True)
        assert resposta.status_code == 200 and "text/html" in resposta.headers["content-type"]
        assert "Painel do dono" in resposta.text and "painel.js" in resposta.text and "painel.css" in resposta.text
        assert "Bearer" not in resposta.text and "cash_debt" not in resposta.text


def test_arquivos_estaticos_do_painel_existem_e_tem_o_tipo_certo(client):
    js = client.get("/painel/painel.js")
    css = client.get("/painel/painel.css")
    assert js.status_code == css.status_code == 200
    assert "javascript" in js.headers["content-type"] and "css" in css.headers["content-type"]


@pytest.mark.parametrize("caminho", ["/painel/../app/main.py", "/painel/%2e%2e/app/main.py", "/painel/nao-existe.js"])
def test_pasta_nao_e_listada_nem_sai_do_diretorio(client, caminho):
    assert client.get(caminho).status_code == 404


def test_toda_rota_chamada_pelo_javascript_existe_na_api(client):
    fonte = JS.read_text(encoding="utf-8")
    fonte = re.sub(r'"\s*\+\s*[A-Za-z_.]+\([^()]*\)\s*\+\s*"', "{}", fonte)       # "/a/" + encodeURIComponent(id) + "/b"
    fonte = re.sub(r'"\s*\+\s*[A-Za-z_.]+\([^()]*\)', '{}"', fonte)                 # "/a/" + encodeURIComponent(id)
    chamados = {re.sub(r"\$\{[^}]*\}", "{}", m) for m in re.findall(r"/v1/[A-Za-z0-9_\-/{}$.]+", fonte)}
    assert len(chamados) >= 15
    conhecidos = {re.sub(r"\{[^}]*\}", "{}", caminho) for caminho in client.app.openapi()["paths"]}
    faltam = sorted(c for c in chamados if c.rstrip("/") not in conhecidos)
    assert faltam == []


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para conferir a sintaxe")
def test_javascript_tem_sintaxe_valida():
    resultado = subprocess.run(["node", "--check", str(JS)], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar a função de escape")
def test_texto_da_api_nunca_entra_como_html():
    codigo = f"const p = require({str(JS)!r}); console.log(p.esc('<script>alert(1)</script> & \"x\"'));"
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    assert "<script>" not in saida.stdout and "&lt;script&gt;" in saida.stdout and "&amp;" in saida.stdout


def test_toda_expressao_dos_modelos_de_html_passa_por_funcao_de_escape():
    fonte = JS.read_text(encoding="utf-8")
    seguras = ("esc(", "money(", "when(", "attr(", "raw(")
    soltas = [e for e in re.findall(r"\$\{([^}]*)\}", fonte) if not e.strip().startswith(seguras) and "/v1/" not in fonte[max(0, fonte.find("${" + e) - 60): fonte.find("${" + e)]]
    assert soltas == [], soltas
