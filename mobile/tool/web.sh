#!/usr/bin/env bash
# Os dois apps dentro do navegador, para conferir as telas e o fluxo sem celular (só desenvolvimento).
#
#   tool/web.sh build [passenger|rider]   gera os apps para a web (perfil, não release: o release recusa http)
#   tool/web.sh up                        servidor descartável (8100) + passageiro (8081) + motoqueiro (8082)
#   tool/web.sh down                      derruba tudo e apaga o banco descartável
#   tool/web.sh status
#
# Depois abra http://localhost:8081/celular.html (passageiro) e http://localhost:8082/celular.html (motoqueiro; sem
# `celular.html` o app ocupa a janela inteira). O código de login sai em
# `curl "http://127.0.0.1:8100/v1/dev/otp?phone=75999990001"`. O administrador do servidor descartável fica em
# `$RUN/sandbox.env` (ADMIN_PHONE); o painel é http://127.0.0.1:8100/painel.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$AQUI/.web-run"
API_PORT=8100
export PATH="$HOME/development/flutter/bin:$PATH"

build() {
  local app
  for app in ${1:-passenger rider}; do
    (cd "$AQUI/apps/$app" && nice -n 10 flutter build web --profile --dart-define="API_URL=http://127.0.0.1:$API_PORT")
  done
}

# `celular.html`: o app dentro de uma moldura de celular (390x844), para as telas terem o tamanho que terão de verdade.
moldura() {
  cat >"$1/celular.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Celular</title>
<style>body{margin:0;background:#2b2e33;display:grid;place-items:center;min-height:100vh}
iframe{width:390px;height:844px;border:0;border-radius:28px;background:#fff;box-shadow:0 0 0 8px #0b0d11}</style>
<iframe src="/index.html" allow="geolocation; camera"></iframe>
HTML
}

up() {
  mkdir -p "$RUN"
  [ -d "$AQUI/apps/passenger/build/web" ] && [ -d "$AQUI/apps/rider/build/web" ] || { echo "Rode antes: tool/web.sh build" >&2; exit 1; }
  down quiet
  moldura "$AQUI/apps/passenger/build/web"
  moldura "$AQUI/apps/rider/build/web"
  : > "$RUN/sandbox.env"
  (cd "$AQUI/../server" && setsid nohup .venv/bin/python scripts/sandbox_server.py --out "$RUN/sandbox.env" --port "$API_PORT" --redis-db 11 >"$RUN/servidor.log" 2>&1 & echo $! >"$RUN/servidor.pid")
  for _ in $(seq 1 240); do [ -s "$RUN/sandbox.env" ] && break; sleep 0.5; done
  [ -s "$RUN/sandbox.env" ] || { echo "O servidor não subiu:" >&2; cat "$RUN/servidor.log" >&2; exit 1; }
  (setsid nohup python3 -m http.server 8081 --bind 127.0.0.1 --directory "$AQUI/apps/passenger/build/web" >"$RUN/passageiro.log" 2>&1 & echo $! >"$RUN/passageiro.pid")
  (setsid nohup python3 -m http.server 8082 --bind 127.0.0.1 --directory "$AQUI/apps/rider/build/web" >"$RUN/motoqueiro.log" 2>&1 & echo $! >"$RUN/motoqueiro.pid")
  echo "Servidor: http://127.0.0.1:$API_PORT   Painel: http://127.0.0.1:$API_PORT/painel"
  echo "Passageiro: http://localhost:8081/celular.html   Motoqueiro: http://localhost:8082/celular.html"
  cat "$RUN/sandbox.env"
}

down() {
  local nome
  [ -d "$RUN" ] || return 0
  for nome in passageiro motoqueiro; do
    [ -f "$RUN/$nome.pid" ] && kill "$(cat "$RUN/$nome.pid")" 2>/dev/null || true
    rm -f "$RUN/$nome.pid"
  done
  if [ -f "$RUN/servidor.pid" ]; then
    # SIGTERM: o servidor descartável apaga esquema, Redis e fotos ao sair
    kill -TERM "$(cat "$RUN/servidor.pid")" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$(cat "$RUN/servidor.pid")" 2>/dev/null || break; sleep 0.5; done
    rm -f "$RUN/servidor.pid"
  fi
  [ "${1:-}" = quiet ] || echo "Tudo derrubado."
}

status() {
  local nome
  for nome in servidor passageiro motoqueiro; do
    if [ -f "$RUN/$nome.pid" ] && kill -0 "$(cat "$RUN/$nome.pid")" 2>/dev/null; then echo "$nome: no ar"; else echo "$nome: parado"; fi
  done
}

case "${1:-}" in
  build) shift; build "$@" ;;
  up) up ;;
  down) down ;;
  status) status ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
