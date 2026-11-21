"""Rotas do Google: leitura da resposta, pedido certo, e a estimativa de reserva quando algo dá errado."""
import json
import logging
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.adapters.fake_maps import FakeMaps
from app.adapters.google_maps import ROUTES_URL, GoogleMaps, decode_polyline, urllib_post
from app.domain.geo import GeoPoint
from app.domain.maps import Route

CODIFICADA = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"          # exemplo da documentação do Google
BOA = {"routes": [{"distanceMeters": 2310, "duration": "412s", "polyline": {"encodedPolyline": CODIFICADA}}]}
ORIGEM = GeoPoint(-12.9644, -39.2597)
DESTINO = GeoPoint(-12.9500, -39.2500)
MASCARA_ROTA = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"


class Post:
    """Chamador de mentira: guarda cada chamada e devolve (ou levanta) as respostas dadas, repetindo a última."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, url, headers, body, timeout_s):
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout_s": timeout_s})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def maps(post, **kw):
    return GoogleMaps("chave-secreta", post=post, **kw)


def test_decode_polyline_do_exemplo_do_google():
    pontos = decode_polyline(CODIFICADA)
    assert [(round(p.lat, 5), round(p.lng, 5)) for p in pontos] == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert decode_polyline("") == ()


def test_rota_boa_vira_route_com_distancia_tempo_e_tracado():
    assert maps(Post(BOA)).route(ORIGEM, DESTINO) == Route(2310, 412, decode_polyline(CODIFICADA))


def test_pedido_vai_com_chave_no_cabecalho_mascara_de_campos_e_corpo_certo():
    post = Post(BOA)
    maps(post).route(ORIGEM, DESTINO)
    (chamada,) = post.calls
    assert chamada["url"] == ROUTES_URL
    assert chamada["headers"]["X-Goog-Api-Key"] == "chave-secreta"
    assert chamada["headers"]["X-Goog-FieldMask"] == MASCARA_ROTA
    assert chamada["body"]["origin"]["location"]["latLng"] == {"latitude": ORIGEM.lat, "longitude": ORIGEM.lng}
    assert chamada["body"]["destination"]["location"]["latLng"] == {"latitude": DESTINO.lat, "longitude": DESTINO.lng}
    assert chamada["body"]["travelMode"] == "DRIVE"
    assert chamada["body"]["routingPreference"] == "TRAFFIC_UNAWARE"
    assert chamada["timeout_s"] == 3.0
    assert "chave-secreta" not in json.dumps({"url": chamada["url"], "body": chamada["body"]})


def test_modo_moto_vai_no_corpo():
    post = Post(BOA)
    maps(post, travel_mode="TWO_WHEELER").route(ORIGEM, DESTINO)
    assert post.calls[0]["body"]["travelMode"] == "TWO_WHEELER"


def test_duracao_com_fracao_arredonda():
    resposta = {"routes": [{"distanceMeters": 500, "duration": "90.6s"}]}
    assert maps(Post(resposta)).route(ORIGEM, DESTINO).duration_s == 91


def test_sem_polilinha_o_tracado_e_origem_e_destino():
    resposta = {"routes": [{"distanceMeters": 500, "duration": "60s"}]}
    assert maps(Post(resposta)).route(ORIGEM, DESTINO).points == (ORIGEM, DESTINO)


def test_eta_usa_so_a_duracao():
    post = Post(BOA)
    assert maps(post).eta_seconds(ORIGEM, DESTINO) == 412
    assert post.calls[0]["headers"]["X-Goog-FieldMask"] == "routes.duration"


@pytest.mark.parametrize(
    "resposta",
    [
        {},
        {"routes": []},
        {"routes": [{}]},
        {"routes": [{"distanceMeters": "abc", "duration": "1s"}]},
        {"routes": [{"distanceMeters": 100, "duration": "rapido"}]},
        {"routes": [{"distanceMeters": 0, "duration": "1s"}]},
        {"routes": [{"distanceMeters": 100}]},
        ["lixo"],
    ],
)
def test_resposta_sem_rota_cai_na_estimativa(resposta):
    assert maps(Post(resposta)).route(ORIGEM, DESTINO) == FakeMaps().route(ORIGEM, DESTINO)


@pytest.mark.parametrize(
    "resposta",
    [{}, {"routes": []}, {"routes": [{}]}, {"routes": [{"duration": "rapido"}]}, {"routes": [{"distanceMeters": 100}]}, ["lixo"]],
)
def test_eta_sem_duracao_legivel_cai_na_estimativa(resposta):
    assert maps(Post(resposta)).eta_seconds(ORIGEM, DESTINO) == FakeMaps().eta_seconds(ORIGEM, DESTINO)


def test_erro_na_chamada_cai_na_estimativa_e_a_chave_nao_vai_para_o_registro(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    resultado = maps(Post(OSError("sem rede"))).route(ORIGEM, DESTINO)
    assert resultado == FakeMaps().route(ORIGEM, DESTINO)
    assert "chave-secreta" not in caplog.text
    assert "Google Maps" in caplog.text and "estimativa" in caplog.text


def test_erro_que_cita_o_endereco_tambem_nao_vaza_a_chave(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    erro = urllib.error.HTTPError(ROUTES_URL, 403, "Forbidden", {}, None)
    maps(Post(erro)).eta_seconds(ORIGEM, DESTINO)
    assert "chave-secreta" not in caplog.text and "HTTPError" in caplog.text


def test_post_padrao_fala_http_de_verdade_com_um_servidor_local():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/nega":
                self.send_response(403)
                self.end_headers()
                return
            resposta = json.dumps({"chave": self.headers["X-Goog-Api-Key"], "corpo": corpo}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resposta)

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{servidor.server_address[1]}"
        resposta = urllib_post(f"{base}/ok", {"X-Goog-Api-Key": "k1"}, {"a": 1}, 3.0)
        assert resposta == {"chave": "k1", "corpo": {"a": 1}}
        with pytest.raises(urllib.error.HTTPError):
            urllib_post(f"{base}/nega", {"X-Goog-Api-Key": "k1"}, {"a": 1}, 3.0)
    finally:
        servidor.shutdown()
        servidor.server_close()


# --- cache, teto diário e pausa -------------------------------------------------------------------------


class Relogio:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def origem(n):
    """Origens bem distintas (cada uma com a sua chave de cache)."""
    return GeoPoint(ORIGEM.lat + 0.01 * n, ORIGEM.lng)


def da_bahia(ano, mes, dia, hora, minuto):
    from datetime import datetime

    from app.domain.clock import LOCAL_TZ

    return datetime(ano, mes, dia, hora, minuto, tzinfo=LOCAL_TZ).timestamp()


def test_mesma_rota_duas_vezes_chama_o_google_uma_vez():
    post = Post(BOA)
    google = maps(post)
    google.route(ORIGEM, DESTINO)
    google.route(ORIGEM, DESTINO)
    assert len(post.calls) == 1
    google.route(GeoPoint(ORIGEM.lat + 0.00001, ORIGEM.lng), DESTINO)     # difere só na 5ª casa: mesma chave
    assert len(post.calls) == 1
    google.route(GeoPoint(ORIGEM.lat + 0.0001, ORIGEM.lng), DESTINO)      # difere na 4ª casa: outra chave
    assert len(post.calls) == 2


def test_cache_da_rota_vence_depois_de_6_horas_e_o_do_tempo_depois_de_2_minutos():
    relogio, post = Relogio(), Post(BOA)
    google = maps(post, clock=relogio)
    google.route(ORIGEM, DESTINO)
    relogio.advance(21_599)
    google.route(ORIGEM, DESTINO)
    assert len(post.calls) == 1
    relogio.advance(2)
    google.route(ORIGEM, DESTINO)
    assert len(post.calls) == 2
    google.eta_seconds(ORIGEM, DESTINO)
    assert len(post.calls) == 3
    relogio.advance(119)
    google.eta_seconds(ORIGEM, DESTINO)
    assert len(post.calls) == 3
    relogio.advance(2)
    google.eta_seconds(ORIGEM, DESTINO)
    assert len(post.calls) == 4


def test_cache_guarda_no_maximo_cache_size_entradas():
    post = Post(BOA)
    google = maps(post, cache_size=2)
    for n in (1, 2, 3):
        google.route(origem(n), DESTINO)
    assert len(post.calls) == 3
    google.route(origem(1), DESTINO)                      # a mais antiga já saiu
    assert len(post.calls) == 4
    google.route(origem(3), DESTINO)                      # as duas mais novas ainda estão
    assert len(post.calls) == 4


def test_estimativa_de_reserva_nao_entra_no_cache():
    post = Post(OSError("sem rede"), BOA)
    google = maps(post)
    primeira = google.route(ORIGEM, DESTINO)
    segunda = google.route(ORIGEM, DESTINO)
    assert primeira == FakeMaps().route(ORIGEM, DESTINO)
    assert segunda == Route(2310, 412, decode_polyline(CODIFICADA))
    assert len(post.calls) == 2


def test_teto_diario_para_de_chamar_e_volta_no_dia_seguinte_da_bahia(caplog):
    caplog.set_level(logging.WARNING, logger="app.google_maps")
    relogio = Relogio(da_bahia(2026, 11, 20, 23, 59))
    post = Post(BOA)
    google = maps(post, clock=relogio, daily_limit=2)
    google.route(origem(1), DESTINO)
    google.route(origem(2), DESTINO)
    barrada = google.route(origem(3), DESTINO)
    assert len(post.calls) == 2 and barrada == FakeMaps().route(origem(3), DESTINO)
    google.route(origem(1), DESTINO)                      # acerto de cache: nem chama nem conta
    google.route(origem(4), DESTINO)                      # outra barrada
    assert len(post.calls) == 2
    assert sum("teto" in r.getMessage() for r in caplog.records) == 1
    relogio.advance(120)                                  # 00:01 do dia 21 na Bahia
    google.route(origem(3), DESTINO)
    assert len(post.calls) == 3


def test_teto_nao_zera_enquanto_o_dia_da_bahia_nao_vira():
    relogio = Relogio(da_bahia(2026, 11, 20, 20, 0))      # 20:00 na Bahia = 23:00 UTC
    post = Post(BOA)
    google = maps(post, clock=relogio, daily_limit=1)
    google.route(origem(1), DESTINO)
    relogio.advance(3600 + 120)                           # 00:02 UTC do dia seguinte, mas só 21:02 na Bahia
    google.route(origem(2), DESTINO)
    assert len(post.calls) == 1


def test_chamada_que_falha_conta_para_o_teto():
    post = Post(OSError("sem rede"))
    google = maps(post, daily_limit=1)
    google.route(origem(1), DESTINO)
    google.route(origem(2), DESTINO)
    assert len(post.calls) == 1


def test_tres_falhas_seguidas_pausam_o_google_por_60_segundos():
    relogio, post = Relogio(), Post(OSError("sem rede"))
    google = maps(post, clock=relogio)
    for n in (1, 2, 3):
        google.route(origem(n), DESTINO)
    assert len(post.calls) == 3
    quarta = google.route(origem(4), DESTINO)
    google.route(origem(5), DESTINO)
    assert len(post.calls) == 3 and quarta == FakeMaps().route(origem(4), DESTINO)
    relogio.advance(61)
    google.route(origem(6), DESTINO)
    assert len(post.calls) == 4


def test_resposta_boa_no_meio_zera_a_contagem_de_falhas():
    erro = OSError("sem rede")
    post = Post(erro, erro, BOA, erro, erro)             # a última se repete
    google = maps(post)
    for n in (1, 2, 3, 4, 5):
        google.route(origem(n), DESTINO)
    assert len(post.calls) == 5                           # nunca 3 falhas seguidas: nenhuma pausa
    google.route(origem(6), DESTINO)                      # a 3ª falha seguida
    assert len(post.calls) == 6
    google.route(origem(7), DESTINO)                      # agora sim, em pausa
    assert len(post.calls) == 6
