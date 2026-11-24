"""Endereço escrito pelo Google (Geocoding API): frase, pedido certo, cache, teto e pausa próprios, e a chave fora do registro."""
import json
import logging
import threading
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import GEOCODE_URL, GoogleMaps, address_text, urllib_get
from app.domain.geo import GeoPoint
from tests.adapters.test_google_maps import BOA, DESTINO, ORIGEM, Post, Relogio, da_bahia

CHAVE = "chave-secreta"
PONTO = GeoPoint(-12.9644, -39.2597)


def resultado(rua="Rua Severo Vieira", numero="120", bairro="São Cristóvão", tipos=("street_address",)):
    partes = []
    if numero:
        partes.append({"long_name": numero, "types": ["street_number"]})
    if rua:
        partes.append({"long_name": rua, "types": ["route"]})
    if bairro:
        partes.append({"long_name": bairro, "types": ["sublocality_level_1", "sublocality", "political"]})
    partes.append({"long_name": "Santo Antônio de Jesus", "types": ["administrative_area_level_2", "political"]})
    return {"types": list(tipos), "address_components": partes, "formatted_address": f"{rua}, {numero} - {bairro}, Santo Antônio de Jesus - BA, Brasil"}


OK = {"status": "OK", "results": [resultado()]}


class Get:
    """Chamador de mentira do endereço: guarda cada URL e devolve (ou levanta) as respostas, repetindo a última."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, url, timeout_s):
        self.calls.append({"url": url, "timeout_s": timeout_s})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def mapa(get, **kw):
    return GoogleMaps(CHAVE, get=get, **kw)


def ponto(n):
    """Pontos bem distintos (cada um com a sua chave de cache)."""
    return GeoPoint(PONTO.lat + 0.01 * n, PONTO.lng)


# --- a frase ---------------------------------------------------------------------------------------------


def test_rua_numero_e_bairro_viram_a_frase():
    assert mapa(Get(OK)).describe(PONTO) == "Rua Severo Vieira, 120 - São Cristóvão"


def test_sem_numero_fica_so_a_rua_e_o_bairro():
    resposta = {"status": "OK", "results": [resultado(numero=None)]}
    assert address_text(resposta) == "Rua Severo Vieira - São Cristóvão"


def test_sem_bairro_fica_so_a_rua_e_o_numero():
    resposta = {"status": "OK", "results": [resultado(bairro=None)]}
    assert address_text(resposta) == "Rua Severo Vieira, 120"


def test_bairro_igual_a_rua_nao_repete():
    resposta = {"status": "OK", "results": [resultado(rua="Centro", numero=None, bairro="Centro")]}
    assert address_text(resposta) == "Centro"


def test_pula_o_resultado_sem_rua_e_usa_o_primeiro_que_tem():
    sem_rua = resultado(rua=None, numero=None, tipos=("neighborhood",))
    resposta = {"status": "OK", "results": [sem_rua, resultado()]}
    assert address_text(resposta) == "Rua Severo Vieira, 120 - São Cristóvão"


def test_so_com_bairro_usa_as_duas_primeiras_partes_do_endereco_formatado():
    so_bairro = resultado(rua=None, numero=None, tipos=("neighborhood",))
    so_bairro["formatted_address"] = "São Cristóvão, Santo Antônio de Jesus - BA, Brasil"
    assert address_text({"status": "OK", "results": [so_bairro]}) == "São Cristóvão - Santo Antônio de Jesus - BA"


def test_frase_nunca_passa_de_200_caracteres():
    resposta = {"status": "OK", "results": [resultado(rua="R" * 400)]}
    assert len(address_text(resposta)) == 200


def test_zero_resultados_e_sem_endereco_e_nao_e_falha_do_servico(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    get = Get({"status": "ZERO_RESULTS", "results": []})
    google = mapa(get)
    for n in (1, 2, 3, 4, 5):
        assert google.describe(ponto(n)) is None
    assert len(get.calls) == 5                                # nenhuma pausa: o Google respondeu direito
    assert "falhou" not in caplog.text


# --- o pedido --------------------------------------------------------------------------------------------


def test_pedido_vai_com_ponto_idioma_tipos_de_resultado_e_chave():
    get = Get(OK)
    mapa(get).describe(PONTO)
    (chamada,) = get.calls
    base, _, consulta = chamada["url"].partition("?")
    assert base == GEOCODE_URL
    assert urllib.parse.parse_qs(consulta) == {
        "latlng": ["-12.964400,-39.259700"], "language": ["pt-BR"],
        "result_type": ["street_address|route|premise|subpremise|neighborhood|sublocality"], "key": [CHAVE],
    }
    assert chamada["timeout_s"] == 3.0


# --- cache -----------------------------------------------------------------------------------------------


def test_mesmo_ponto_duas_vezes_chama_o_google_uma_vez_e_ponto_vizinho_chama_outra():
    get = Get(OK)
    google = mapa(get)
    google.describe(PONTO)
    google.describe(PONTO)
    google.describe(GeoPoint(PONTO.lat + 0.000001, PONTO.lng))        # 6ª casa: mesma chave
    assert len(get.calls) == 1
    google.describe(GeoPoint(PONTO.lat + 0.00001, PONTO.lng))         # 5ª casa (≈ 1 m): outra chave
    assert len(get.calls) == 2


def test_cache_guarda_tambem_o_ponto_sem_endereco_e_vence_em_24_horas():
    relogio = Relogio()
    get = Get({"status": "ZERO_RESULTS"})
    google = mapa(get, clock=relogio)
    google.describe(PONTO)
    google.describe(PONTO)
    assert len(get.calls) == 1
    relogio.advance(24 * 3600 - 1)
    google.describe(PONTO)
    assert len(get.calls) == 1
    relogio.advance(2)
    google.describe(PONTO)
    assert len(get.calls) == 2


def test_falha_nao_entra_no_cache():
    get = Get(OSError("sem rede"), OK)
    google = mapa(get)
    assert google.describe(PONTO) is None
    assert google.describe(PONTO) == "Rua Severo Vieira, 120 - São Cristóvão"
    assert len(get.calls) == 2


# --- falhas, teto e pausa --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resposta",
    [{"status": "REQUEST_DENIED", "error_message": "API key invalid"}, {"status": "OVER_QUERY_LIMIT"}, {"status": "UNKNOWN_ERROR"},
     {"status": "INVALID_REQUEST"}, {}, ["lixo"], "lixo", OSError("sem rede"), TimeoutError()],
)
def test_resposta_ruim_ou_erro_de_rede_vira_sem_endereco_e_nao_levanta(resposta):
    assert mapa(Get(resposta)).describe(PONTO) is None


def test_a_chave_nunca_vai_para_o_registro_nem_em_erro_que_cita_a_url(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    url_com_chave = f"{GEOCODE_URL}?key={CHAVE}"
    erro = urllib.error.HTTPError(url_com_chave, 403, f"Forbidden {url_com_chave}", {}, None)
    mapa(Get(erro)).describe(PONTO)
    mapa(Get(OSError(f"falhou em {url_com_chave}"))).describe(ponto(1))
    assert CHAVE not in caplog.text
    assert "Google Maps" in caplog.text and "sem endereço" in caplog.text


def test_teto_diario_de_enderecos_para_de_chamar_e_volta_no_dia_seguinte_da_bahia(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    relogio = Relogio(da_bahia(2026, 11, 20, 23, 59))
    get = Get(OK)
    google = mapa(get, clock=relogio, geocode_daily_limit=2)
    google.describe(ponto(1))
    google.describe(ponto(2))
    assert google.describe(ponto(3)) is None
    google.describe(ponto(1))                                          # acerto de cache: nem chama nem conta
    google.describe(ponto(4))                                          # outra barrada
    assert len(get.calls) == 2
    assert sum("teto" in r.getMessage() and "endereços" in r.getMessage() for r in caplog.records) == 1
    relogio.advance(120)                                               # 00:01 do dia 21 na Bahia
    assert google.describe(ponto(3)) == "Rua Severo Vieira, 120 - São Cristóvão"
    assert len(get.calls) == 3


def test_tres_falhas_seguidas_pausam_o_endereco_por_60_segundos():
    relogio, get = Relogio(), Get(OSError("sem rede"))
    google = mapa(get, clock=relogio)
    for n in (1, 2, 3):
        google.describe(ponto(n))
    google.describe(ponto(4))
    google.describe(ponto(5))
    assert len(get.calls) == 3
    relogio.advance(61)
    google.describe(ponto(6))
    assert len(get.calls) == 4


def test_endereco_e_rotas_tem_tetos_e_pausas_separados():
    # o teto de rotas esgotado não barra o endereço...
    post, get = Post(BOA), Get(OK)
    google = GoogleMaps(CHAVE, post=post, get=get, daily_limit=1)
    google.route(ORIGEM, DESTINO)
    assert google.route(GeoPoint(ORIGEM.lat + 0.01, ORIGEM.lng), DESTINO) == FakeMaps().route(GeoPoint(ORIGEM.lat + 0.01, ORIGEM.lng), DESTINO)
    assert google.describe(PONTO) == "Rua Severo Vieira, 120 - São Cristóvão"
    # ...nem o endereço esgotado barra as rotas
    post, get = Post(BOA), Get(OK)
    google = GoogleMaps(CHAVE, post=post, get=get, geocode_daily_limit=1)
    google.describe(ponto(1))
    assert google.describe(ponto(2)) is None
    google.route(ORIGEM, DESTINO)
    assert len(post.calls) == 1 and len(get.calls) == 1


def test_falhas_do_endereco_nao_pausam_as_rotas_e_as_das_rotas_nao_pausam_o_endereco():
    post, get = Post(BOA), Get(OSError("sem rede"))
    google = GoogleMaps(CHAVE, post=post, get=get)
    for n in (1, 2, 3):
        google.describe(ponto(n))                                      # pausa só o endereço
    google.route(ORIGEM, DESTINO)
    assert len(post.calls) == 1
    post, get = Post(OSError("sem rede")), Get(OK)
    google = GoogleMaps(CHAVE, post=post, get=get)
    for n in (1, 2, 3):
        google.route(GeoPoint(ORIGEM.lat + 0.01 * n, ORIGEM.lng), DESTINO)   # pausa só as rotas
    assert google.describe(PONTO) is not None


def test_mapa_falso_nao_inventa_endereco():
    assert FakeMaps().describe(PONTO) is None


# --- o chamador de verdade -------------------------------------------------------------------------------


def test_get_padrao_fala_http_de_verdade_com_um_servidor_local():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/nega"):
                self.send_response(403)
                self.end_headers()
                return
            consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            corpo = json.dumps({"status": "OK", "results": [], "eco": consulta}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{servidor.server_address[1]}"
        assert urllib_get(f"{base}/ok?latlng=1,2&key=k1", 3.0)["eco"] == {"latlng": ["1,2"], "key": ["k1"]}
        with pytest.raises(urllib.error.HTTPError):
            urllib_get(f"{base}/nega?key=k1", 3.0)
    finally:
        servidor.shutdown()
        servidor.server_close()


# --- ruas de mentira (demonstração) ---------------------------------------------------------------------


def test_ruas_em_escada_andam_na_vertical_e_na_horizontal_e_a_distancia_e_a_do_percurso():
    from app.adapters.fake_maps import StreetGridMaps
    from app.domain.geo import haversine_m

    origem, destino = GeoPoint(-12.96, -39.26), GeoPoint(-12.97, -39.25)
    rota = StreetGridMaps().route(origem, destino)
    assert rota.points[0] == origem and rota.points[-1].lat == pytest.approx(destino.lat)
    assert rota.points[-1].lng == pytest.approx(destino.lng)
    assert len(rota.points) == 7                                       # 3 degraus: 6 trechos
    for a, b in zip(rota.points, rota.points[1:]):
        assert a.lat == b.lat or a.lng == b.lng                       # cada trecho é vertical ou horizontal
    assert rota.distance_m == round(sum(haversine_m(a, b) for a, b in zip(rota.points, rota.points[1:])))
    assert rota.distance_m > haversine_m(origem, destino) * 1.3 * 0.9   # mais longa que a reta
    assert StreetGridMaps().describe(origem) is None
