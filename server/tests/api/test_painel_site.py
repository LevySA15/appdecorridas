"""O site do painel: servido sem login, sem dado nenhum, e coerente com a API que ele chama."""
import json
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
    from app.api.routes import ws as rotas_ws

    conhecidos |= {rota.path for rota in rotas_ws.router.routes}            # o WebSocket não aparece no openapi
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


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar as ações")
def test_acao_cancelada_no_prompt_nao_conta_como_feita_e_a_confirmada_sim():
    codigo = f"""
global.document = undefined; global.window = {{ prompt: () => null }}; global.fetch = async () => ({{ status: 204, ok: true }});
global.sessionStorage = {{ getItem: () => 't', setItem() {{}}, removeItem() {{}} }};
const p = require({str(JS)!r});
(async () => {{
  const cancelada = await p.ACOES['rider-reject']('r1');
  global.window.prompt = () => 'foto ruim';
  const feita = await p.ACOES['rider-reject']('r1');
  console.log(JSON.stringify({{ cancelada: cancelada === p.CANCELADO, feita: feita === p.CANCELADO }}));
}})();
"""
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == '{"cancelada":true,"feita":false}'


def test_sair_encerra_a_sessao_no_servidor():
    assert "/v1/auth/logout" in JS.read_text(encoding="utf-8")


def test_painel_mostra_o_reenvio_do_cadastro_e_quem_pediu_o_alerta():
    fonte = JS.read_text(encoding="utf-8")
    assert "previous_rejection" in fonte and "resubmissions" in fonte and "raised_by" in fonte


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar as funções do painel")
@pytest.mark.parametrize(
    "item, esperado",
    [
        ({"status": "pending", "reason": None, "resubmissions": 0, "previous_rejection": None}, "pending"),
        (
            {"status": "pending", "reason": None, "resubmissions": 2, "previous_rejection": "Foto <b>ruim</b>"},
            "pending · reenvio nº 2 (recusado antes: Foto <b>ruim</b>)",
        ),
        ({"status": "rejected", "reason": "CNH vencida", "resubmissions": 1, "previous_rejection": None}, "rejected: CNH vencida"),
    ],
)
def test_texto_da_situacao_do_cadastro(item, esperado):
    import json

    codigo = f"const p = require({str(JS)!r}); console.log(p.situacaoDoCadastro({json.dumps(item)}));"
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == esperado


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar as funções do painel")
@pytest.mark.parametrize(
    "alerta, esperado",
    [
        ({"kind": "stopped", "suspected_mock": False, "raised_by": "system"}, "stopped"),
        ({"kind": "stopped", "suspected_mock": True, "raised_by": "system"}, "stopped (localização suspeita)"),
        ({"kind": "sos", "suspected_mock": False, "raised_by": "passenger"}, "sos · pelo passageiro"),
        ({"kind": "sos", "suspected_mock": False, "raised_by": "rider"}, "sos · pelo motoqueiro"),
    ],
)
def test_texto_do_tipo_do_alerta(alerta, esperado):
    import json

    codigo = f"const p = require({str(JS)!r}); console.log(p.tipoDoAlerta({json.dumps(alerta)}));"
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == esperado


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar as funções do painel")
@pytest.mark.parametrize(
    "item, esperado",
    [
        ({"documents": ["selfie", "cnh", "crlv"]}, ["selfie", "cnh", "crlv"]),
        ({"documents": ["cnh"]}, ["cnh"]),            # as outras já foram apagadas (recusado há mais de 30 dias)
        ({"documents": []}, []),
    ],
)
def test_so_mostra_botao_das_fotos_que_ainda_existem(item, esperado):
    import json

    codigo = f"const p = require({str(JS)!r}); console.log(JSON.stringify(p.fotosDoCadastro({json.dumps(item)})));"
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    assert json.loads(saida.stdout) == esperado


def _rodar_node(codigo: str) -> str:
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True)
    assert saida.returncode == 0, saida.stderr
    return saida.stdout.strip()


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar as telas")
def test_tela_de_saques_mostra_valor_e_chave_mascarada_sem_deixar_texto_virar_html():
    codigo = f"""
global.document = undefined;
global.sessionStorage = {{ getItem: () => 't', setItem() {{}}, removeItem() {{}} }};
const lista = [{{ withdrawal_id: 'w1', passenger_id: 'p1', passenger_name: '<b>Ana</b>', amount_cents: 2500,
                  key_kind: 'phone', key_masked: '***-0001', created_at: 1800000000 }}];
let chamado = null;
global.fetch = async (url) => {{ chamado = url; return {{ status: 200, ok: true, json: async () => lista }}; }};
const p = require({str(JS)!r});
(async () => {{
  const html = await p.VISOES.saques();
  lista.length = 0;
  const vazio = await p.VISOES.saques();
  console.log(JSON.stringify({{ chamado, html, vazio, telas: Object.keys(p.TELAS) }}));
}})();
"""
    r = json.loads(_rodar_node(codigo))
    assert r["chamado"].startswith("/v1/admin/withdrawals")
    assert "R$ 25,00" in r["html"] and "***-0001" in r["html"] and "Chave" in r["html"]
    assert "&lt;b&gt;Ana&lt;/b&gt;" in r["html"] and "<b>Ana</b>" not in r["html"]
    assert "Nada por aqui." in r["vazio"]
    assert r["telas"].index("saques") == r["telas"].index("dinheiro") + 1


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar os avisos ao vivo")
@pytest.mark.parametrize(
    "mensagem, esperado",
    [
        ({"type": "sos", "data": {"raised_by": "rider"}}, {"texto": "SOS pelo motoqueiro", "tela": "alertas", "urgente": True}),
        ({"type": "sos", "data": {"raised_by": "passenger"}}, {"texto": "SOS pelo passageiro", "tela": "alertas", "urgente": True}),
        ({"type": "sos", "data": {}}, {"texto": "SOS", "tela": "alertas", "urgente": True}),
        ({"type": "safety_alert", "data": {"kind": "stopped"}}, {"texto": "Alerta de segurança: parou", "tela": "alertas", "urgente": False}),
        ({"type": "safety_alert", "data": {"kind": "off_route"}}, {"texto": "Alerta de segurança: saiu da rota", "tela": "alertas", "urgente": False}),
        ({"type": "safety_alert", "data": {"kind": "no_signal"}}, {"texto": "Alerta de segurança: sem sinal", "tela": "alertas", "urgente": False}),
        ({"type": "mock_location_suspected", "data": {"ride_id": "x"}}, {"texto": "Localização suspeita numa corrida", "tela": "alertas", "urgente": False}),
        ({"type": "appeal_opened", "data": {"ride_id": "x"}}, {"texto": "Novo recurso de taxa de cancelamento", "tela": "recursos", "urgente": False}),
        ({"type": "safety_ok", "data": {}}, None),
        ({"type": "ready", "data": {"user_id": "a"}}, None),
        ({"type": "coisa_nova", "data": {}}, None),
        (None, None),
    ],
)
def test_texto_do_aviso_ao_vivo(mensagem, esperado):
    codigo = f"global.document = undefined; const p = require({str(JS)!r}); console.log(JSON.stringify(p.descreverAviso({json.dumps(mensagem)})));"
    assert json.loads(_rodar_node(codigo)) == esperado


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar a conexão ao vivo")
def test_conexao_ao_vivo_manda_o_token_reconecta_sozinha_e_para_quando_mandam():
    codigo = f"""
global.document = undefined;
const p = require({str(JS)!r});
const sockets = [], tarefas = [], recebidas = [];
class Falso {{
  constructor() {{ sockets.push(this); this.enviado = []; this.fechado = false; }}
  send(m) {{ this.enviado.push(m); }}
  close() {{ this.fechado = true; if (this.onclose) this.onclose({{ code: 1000 }}); }}
}}
let recusou = 0;
const agendar = (fn, ms) => {{ tarefas.push({{ fn, ms }}); return tarefas.length; }};
const ligacao = p.conectarAvisos({{ criarSocket: () => new Falso(), agendar, cancelar() {{}}, token: 'tok', aoMensagem: (m) => recebidas.push(m), aoRecusar: () => {{ recusou += 1; }} }});
const s0 = sockets[0];
s0.onopen();
s0.onmessage({{ data: JSON.stringify({{ type: 'sos', data: {{}} }}) }});
s0.onmessage({{ data: 'isto não é json' }});                      // mensagem ruim não derruba a conexão
s0.onclose({{ code: 1006 }});                                       // caiu: agenda outra tentativa
const depoisDeCair = {{ tarefas: tarefas.length, ms: tarefas[0].ms, sockets: sockets.length }};
tarefas[0].fn();
const depoisDeReconectar = sockets.length;
const s1 = sockets[1];
s1.onclose({{ code: 1006 }});
ligacao.fechar();                                                    // a pessoa saiu do painel
tarefas[1].fn();                                                     // a tentativa que estava agendada não abre nada
const depoisDeFechar = sockets.length;
const outra = p.conectarAvisos({{ criarSocket: () => new Falso(), agendar, cancelar() {{}}, token: 'tok', aoMensagem() {{}}, aoRecusar: () => {{ recusou += 1; }} }});
const agendadasAntes = tarefas.length;
sockets[sockets.length - 1].onclose({{ code: 4401 }});               // o servidor diz que a sessão acabou
console.log(JSON.stringify({{ enviado: s0.enviado, recebidas, depoisDeCair, depoisDeReconectar, depoisDeFechar, recusou,
  agendouAposRecusa: tarefas.length - agendadasAntes }}));
"""
    r = json.loads(_rodar_node(codigo))
    assert r["enviado"] == ['{"token":"tok"}']
    assert r["recebidas"] == [{"type": "sos", "data": {}}]
    assert r["depoisDeCair"] == {"tarefas": 1, "ms": 3000, "sockets": 1}
    assert r["depoisDeReconectar"] == 2
    assert r["depoisDeFechar"] == 2
    assert r["recusou"] == 1 and r["agendouAposRecusa"] == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="sem node para rodar o aviso na tela")
def test_aviso_ao_vivo_na_tela_nunca_vira_html_conta_os_seguintes_e_recarrega_a_lista():
    codigo = f"""
global.document = undefined;
global.sessionStorage = {{ getItem: () => 't', setItem() {{}}, removeItem() {{}} }};
const chamadas = [];
global.fetch = async (url) => {{ chamadas.push(url); return {{ status: 200, ok: true, json: async () => [] }}; }};
const p = require({str(JS)!r});
const caixas = {{ 'alerta-vivo': {{ hidden: true, textContent: '', className: '' }}, tela: {{ hidden: true, innerHTML: '' }},
  aviso: {{ textContent: '', className: '' }}, detalhe: {{ hidden: true }}, menu: {{ children: [] }} }};
global.document = {{ title: 'Painel do dono', getElementById: (id) => caixas[id] }};
(async () => {{
  await p.mostrar('alertas');
  const antes = chamadas.filter((u) => u.includes('safety-alerts')).length;
  p.aoAviso({{ type: 'sos', data: {{ raised_by: '<img src=x onerror=alert(1)>' }} }});
  const primeiro = {{ texto: caixas['alerta-vivo'].textContent, titulo: document.title, escondida: caixas['alerta-vivo'].hidden, classe: caixas['alerta-vivo'].className }};
  p.aoAviso({{ type: 'safety_alert', data: {{ kind: 'stopped' }} }});
  const segundo = caixas['alerta-vivo'].textContent;
  const classeDepoisDoSegundo = caixas['alerta-vivo'].className;
  await new Promise((r) => setTimeout(r, 20));
  const recarregou = chamadas.filter((u) => u.includes('safety-alerts')).length > antes;
  await p.mostrar('cadastros');
  const antesRecursos = chamadas.filter((u) => u.includes('appeals')).length;
  p.aoAviso({{ type: 'appeal_opened', data: {{}} }});
  await new Promise((r) => setTimeout(r, 20));
  const naoRecarregouOutraTela = chamadas.filter((u) => u.includes('appeals')).length === antesRecursos;
  p.limparAviso();
  console.log(JSON.stringify({{ primeiro, segundo, classeDepoisDoSegundo, recarregou, naoRecarregouOutraTela, depois: {{ escondida: caixas['alerta-vivo'].hidden, titulo: document.title }} }}));
}})();
"""
    r = json.loads(_rodar_node(codigo))
    assert r["primeiro"]["texto"].startswith("SOS") and "clique para ver" in r["primeiro"]["texto"]
    assert r["primeiro"]["titulo"] == "(!) " + r["primeiro"]["texto"].split(" — ")[0] + " — Painel do dono"
    assert r["primeiro"]["escondida"] is False and "urgente" in r["primeiro"]["classe"]
    assert r["segundo"].startswith("SOS") and "(+1)" in r["segundo"]            # um aviso comum não apaga o SOS da caixa
    assert "urgente" in r["classeDepoisDoSegundo"]
    assert r["recarregou"] is True and r["naoRecarregouOutraTela"] is True
    assert r["depois"] == {"escondida": True, "titulo": "Painel do dono"}
