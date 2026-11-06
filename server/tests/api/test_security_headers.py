"""Cabeçalhos de segurança: em toda resposta, e a política de conteúdo só no site do painel."""
import re
from pathlib import Path

import pytest

PAINEL = Path(__file__).resolve().parents[2] / "painel"

BASICOS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


@pytest.mark.parametrize("caminho", ["/health", "/v1/rider/state", "/nao-existe"])
def test_toda_resposta_traz_os_cabecalhos_basicos(client, caminho):
    resposta = client.get(caminho)
    for nome, valor in BASICOS.items():
        assert resposta.headers.get(nome) == valor, f"{nome} faltando em {caminho} ({resposta.status_code})"


@pytest.mark.parametrize("caminho", ["/painel/", "/painel/painel.js", "/painel/painel.css"])
def test_painel_traz_politica_de_conteudo_restrita(client, caminho):
    politica = client.get(caminho).headers["content-security-policy"]
    for exigido in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'"):
        assert exigido in politica
    assert "unsafe-inline" not in politica and "unsafe-eval" not in politica


def test_a_api_nao_leva_a_politica_do_painel(client):
    assert "content-security-policy" not in client.get("/health").headers


def test_painel_cabe_na_politica():
    """Se alguém puser script/estilo dentro da página ou carregar algo de fora, a política quebra o painel
    em silêncio no navegador: este teste avisa antes. Ajuste `PAINEL_CSP` junto com a mudança."""
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    aviso = "o painel passou a usar algo que a política de conteúdo bloqueia: ajuste PAINEL_CSP (app/api/security_headers.py)"
    assert not re.search(r"<script(?![^>]*\bsrc=)", html, re.I), aviso
    assert not re.search(r"<style", html, re.I), aviso
    assert not re.search(r"\sstyle\s*=", html + js, re.I), aviso
    assert not re.search(r"\son[a-z]+\s*=", html + js, re.I), aviso
    assert 'setAttribute("style"' not in js and "setAttribute('style'" not in js, aviso
    assert not re.search(r"https?://", html + js + css), aviso
