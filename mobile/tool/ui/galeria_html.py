#!/usr/bin/env python3
"""Monta UMA página com as fotos das telas (claro e escuro lado a lado). Uso: galeria_html.py <pasta das fotos> <saida.html>

As fotos vêm de `node galeria.js claro|escuro` (SHOT_JPEG=1) e `node painel.js 1280` (SHOT_JPEG=1)."""
import base64
import sys
from pathlib import Path

pasta, saida = Path(sys.argv[1]), Path(sys.argv[2])

PASSAGEIRO = [
    ("01-entrar", "Entrar", "Telefone e código por mensagem."),
    ("02-codigo", "Código recebido", "Os 6 dígitos que chegam no celular."),
    ("03-nome", "Como te chamar", "O motoqueiro vê esse nome ao buscar."),
    ("04-inicio", "Início", "Mapa da cidade, \"Pra onde vamos?\" e atalhos."),
    ("05-marcar-no-mapa", "Marcar no mapa", "Toque no mapa ou use \"Estou aqui\"."),
    ("05b-estou-aqui", "Estou aqui", "O embarque vira a posição do celular."),
    ("06-cotacao", "Preço e pagamento", "Preço único, distância, tempo da moto e forma de pagar."),
    ("07-procurando", "Procurando moto", "Mapa do trajeto, preço e cancelar."),
    ("08-moto-a-caminho", "Moto a caminho", "Ficha do motoqueiro e o código de 4 dígitos."),
    ("09-pix", "Pix", "QR code, copia e cola e botão de copiar."),
    ("10-moto-chegou", "Moto chegou", "O aviso muda e o código continua à vista."),
    ("11-em-viagem", "Em viagem", "Sem cancelar: fica o SOS no alto."),
    ("12-avaliar", "Avaliar", "Estrelas grandes; \"Agora não\" sempre disponível."),
    ("13-carteira", "Carteira", "Saldo, recarregar e sacar."),
    ("14-recarga", "Recarregar", "Diálogo com Cancelar e Confirmar."),
    ("15-historico", "Minhas corridas", "Só as encerradas, da mais nova para a mais antiga."),
    ("16-recibo", "Recibo", "Valor, motoqueiro e forma de pagar."),
    ("17-perfil", "Perfil", "Nome, telefone, contato de emergência e sair."),
]
MOTOQUEIRO = [
    ("01-entrar", "Entrar", "Mesma tela, com a voz do app do motoqueiro."),
    ("02-cadastro", "Cadastro", "Máscaras de CPF, CNH, placa e datas."),
    ("03-em-analise", "Em análise", "Espera a aprovação do dono."),
    ("04-inicio-parado", "Início, parado", "Cartão grande para ligar o \"estou rodando\"."),
    ("05-inicio-rodando", "Início, rodando", "Vermelho ligado, esperando pedidos."),
    ("06-oferta", "Oferta", "Preço, distância, tempo até o passageiro e o trajeto."),
    ("07-a-caminho", "Indo buscar", "Mapa e botão \"Cheguei\"."),
    ("08-cheguei-pedir-codigo", "Conferir o código", "Capacete extra e o código do passageiro."),
    ("09-em-viagem", "Em viagem", "Levando o passageiro até o destino."),
    ("10-avaliar", "Avaliar", "A nota do passageiro."),
    ("11-extrato", "Extrato do dia", "Ganho, taxa do app, Pix e dinheiro."),
]
PAINEL = [
    ("1280-corridas", "Corridas", "Estados em português e páginas de 50."),
    ("1280-dinheiro", "Dinheiro", "Receita, repasses, saldos e livro-caixa."),
    ("1280-parametros", "Parâmetros", "Cada número com nome e unidade."),
    ("1280-cadastros", "Cadastros", "Aprovar ou recusar motoqueiros."),
]


def uri(arquivo: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(arquivo.read_bytes()).decode()


def figura(prefixo: str, chave: str, modo: str, alt: str) -> str:
    arquivo = pasta / f"{prefixo}-{modo}-{chave}.jpg"
    if not arquivo.exists():
        return ""
    return f'<button class="foto {modo}" type="button" data-modo="{modo}" aria-label="Ampliar: {alt} ({modo})"><img loading="lazy" src="{uri(arquivo)}" alt="{alt} ({modo})"></button>'


def secao(prefixo: str, titulo: str, itens) -> str:
    cartoes = []
    for chave, nome, texto in itens:
        fotos = figura(prefixo, chave, "claro", nome) + figura(prefixo, chave, "escuro", nome)
        if fotos:
            cartoes.append(f'<article class="tela"><div class="fotos">{fotos}</div><h3>{nome}</h3><p>{texto}</p></article>')
    return f'<section id="{prefixo}" class="secao" hidden><div class="grade">{"".join(cartoes)}</div></section>', len(cartoes)


def painel() -> tuple[str, int]:
    cartoes = []
    for chave, nome, texto in PAINEL:
        arquivo = pasta / f"painel-{chave}.jpg"
        if arquivo.exists():
            cartoes.append(f'<article class="tela larga"><button class="foto claro largo" type="button" data-modo="claro" aria-label="Ampliar: {nome}"><img loading="lazy" src="{uri(arquivo)}" alt="Painel: {nome}"></button><h3>{nome}</h3><p>{texto}</p></article>')
    return f'<section id="painel" class="secao" hidden><div class="grade">{"".join(cartoes)}</div></section>', len(cartoes)


sp, np = secao("p", "Passageiro", PASSAGEIRO)
sm, nm = secao("m", "Motoqueiro", MOTOQUEIRO)
sd, nd = painel()

html = f"""<title>Telas dos apps do Recôncavo</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;700&display=swap">
<style>
/* Layout: cabeçalho com abas; cada tela vira um cartão com o claro e o escuro lado a lado, e o clique amplia. */
:root {{
  --bg: #F3F2EF; --surface: #FFFFFF; --fg: #17181B; --muted: #686B73; --line: #E2E0DB; --accent: #D92D27; --on-accent: #FFFFFF; --shade: rgba(20,20,24,.72);
  --display: "Space Grotesk", "Inter", system-ui, sans-serif; --text: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg: #111215; --surface: #1A1B20; --fg: #EDEDEF; --muted: #9C9FA8; --line: #2A2C33; --shade: rgba(0,0,0,.82); color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --bg: #111215; --surface: #1A1B20; --fg: #EDEDEF; --muted: #9C9FA8; --line: #2A2C33; --shade: rgba(0,0,0,.82); color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 var(--text); padding-inline: max(16px, env(safe-area-inset-left, 0px)) max(16px, env(safe-area-inset-right, 0px)); padding-block: 24px 56px; }}
header {{ max-width: 1180px; margin: 0 auto 20px; display: grid; gap: 6px; }}
h1 {{ font: 700 clamp(1.6rem, 4vw, 2.3rem)/1.1 var(--display); letter-spacing: -.02em; margin: 0; text-wrap: balance; }}
.sub {{ color: var(--muted); max-width: 70ch; margin: 0; }}
.barra {{ max-width: 1180px; margin: 0 auto 24px; display: flex; flex-wrap: wrap; gap: 10px 20px; align-items: center; justify-content: space-between; }}
.abas, .modos {{ display: flex; flex-wrap: wrap; gap: 6px; }}
button.aba, button.modo {{ font: 600 14px var(--text); color: var(--muted); background: transparent; border: 1px solid var(--line); border-radius: 999px; padding: 8px 14px; cursor: pointer; }}
button.aba[aria-selected="true"] {{ background: var(--accent); border-color: var(--accent); color: var(--on-accent); }}
button.modo[aria-pressed="true"] {{ color: var(--fg); border-color: var(--fg); }}
button:focus-visible {{ outline: 3px solid var(--accent); outline-offset: 2px; }}
.secao {{ max-width: 1180px; margin: 0 auto; }}
.grade {{ display: grid; gap: 22px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr)); }}
.tela {{ min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 14px 14px 16px; display: grid; gap: 8px; align-content: start; }}
.tela.larga {{ grid-column: 1 / -1; }}
.fotos {{ display: flex; gap: 10px; justify-content: center; }}
.foto {{ flex: 1 1 0; min-width: 0; max-width: 250px; padding: 0; border: 0; border-radius: 14px; overflow: hidden; background: #888; cursor: zoom-in; line-height: 0; box-shadow: 0 6px 18px rgba(0,0,0,.14); }}
.foto img {{ width: 100%; height: auto; display: block; aspect-ratio: 390 / 844; object-fit: cover; }}
.foto.largo {{ max-width: 100%; }}
.foto.largo img {{ aspect-ratio: auto; }}
body[data-mostrar="claro"] .foto.escuro, body[data-mostrar="escuro"] .foto.claro {{ display: none; }}
h3 {{ font: 700 1.05rem/1.2 var(--display); margin: 4px 0 0; letter-spacing: -.01em; }}
.tela p {{ margin: 0; color: var(--muted); font-size: .9rem; }}
footer {{ max-width: 1180px; margin: 36px auto 0; color: var(--muted); font-size: .85rem; display: grid; gap: 6px; }}
footer p {{ margin: 0; max-width: 80ch; }}
#caixa {{ position: fixed; inset: 0; background: var(--shade); display: grid; place-items: center; padding: 16px; z-index: 20; }}
#caixa[hidden] {{ display: none; }}
#caixa img {{ max-height: calc(100vh - 32px); max-width: 100%; border-radius: 16px; background: #888; }}
@media (prefers-reduced-motion: no-preference) {{ .foto {{ transition: transform .15s ease; }} .foto:hover {{ transform: translateY(-2px); }} }}
</style>
<header>
  <h1>Telas dos apps do Recôncavo</h1>
  <p class="sub">Passageiro, motoqueiro e painel do dono, como estão hoje (24/11/2026). Cada tela aparece no tema claro e no escuro; toque numa foto para ampliar.</p>
</header>
<div class="barra">
  <div class="abas" role="tablist" aria-label="Qual app">
    <button class="aba" role="tab" id="t-p" aria-selected="true" aria-controls="p" type="button">Passageiro ({np})</button>
    <button class="aba" role="tab" id="t-m" aria-selected="false" aria-controls="m" type="button">Motoqueiro ({nm})</button>
    <button class="aba" role="tab" id="t-painel" aria-selected="false" aria-controls="painel" type="button">Painel ({nd})</button>
  </div>
  <div class="modos" role="group" aria-label="Tema">
    <button class="modo" type="button" data-v="todos" aria-pressed="true">Claro e escuro</button>
    <button class="modo" type="button" data-v="claro" aria-pressed="false">Só claro</button>
    <button class="modo" type="button" data-v="escuro" aria-pressed="false">Só escuro</button>
  </div>
</div>
{sp}
{sm}
{sd}
<footer>
  <p>Fotos tiradas por um navegador sem janela, rodando as versões web dos dois apps contra um servidor de teste (corrida em Pix completa, motoqueiro aprovado pela API, passageiro novo).</p>
  <p>O mapa é o do OpenStreetMap (ruas reais de Santo Antônio de Jesus), que o app de release usa no teste fechado; o mapa do Google entra com a chave. <strong>Nada disto foi visto num celular de verdade ainda.</strong></p>
</footer>
<div id="caixa" hidden role="dialog" aria-modal="true" aria-label="Foto ampliada"><img id="ampliada" alt=""></div>
<script>
(function () {{
  var abas = document.querySelectorAll('.aba'), secoes = {{ p: document.getElementById('p'), m: document.getElementById('m'), painel: document.getElementById('painel') }};
  function mostrar(id) {{
    Object.keys(secoes).forEach(function (k) {{ secoes[k].hidden = k !== id; }});
    abas.forEach(function (a) {{ a.setAttribute('aria-selected', String(a.id === 't-' + id)); }});
    try {{ history.replaceState(null, '', '#' + id); }} catch (e) {{}}
  }}
  abas.forEach(function (a) {{ a.addEventListener('click', function () {{ mostrar(a.id.slice(2)); }}); }});
  var inicial = (location.hash || '#p').slice(1); mostrar(secoes[inicial] ? inicial : 'p');
  window.addEventListener('hashchange', function () {{ var h = location.hash.slice(1); if (secoes[h]) mostrar(h); }});
  document.querySelectorAll('.modo').forEach(function (b) {{ b.addEventListener('click', function () {{
    document.body.dataset.mostrar = b.dataset.v;
    document.querySelectorAll('.modo').forEach(function (o) {{ o.setAttribute('aria-pressed', String(o === b)); }});
  }}); }});
  var caixa = document.getElementById('caixa'), grande = document.getElementById('ampliada');
  document.addEventListener('click', function (e) {{
    var f = e.target.closest('.foto');
    if (f) {{ grande.src = f.querySelector('img').src; grande.alt = f.querySelector('img').alt; caixa.hidden = false; return; }}
    if (!caixa.hidden) caixa.hidden = true;
  }});
  document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') caixa.hidden = true; }});
}})();
</script>
"""
saida.write_text(html, encoding="utf-8")
print(f"{saida} ({saida.stat().st_size / 1e6:.1f} MB; passageiro {np}, motoqueiro {nm}, painel {nd})")
