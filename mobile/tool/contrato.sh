#!/usr/bin/env bash
# Teste de contrato: o cliente Dart (corrida_core) contra um servidor de verdade e descartável.
# Sobe o servidor do simulador, roda `dart test test_contract` e derruba o servidor.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/development/flutter/bin:$PATH"
SAIDA="$(mktemp)"
LOG="$(mktemp)"

(cd "$AQUI/../server" && exec .venv/bin/python scripts/sandbox_server.py --out "$SAIDA") >"$LOG" 2>&1 &
SERVIDOR=$!
cleanup() {
  kill "$SERVIDOR" 2>/dev/null || true
  wait "$SERVIDOR" 2>/dev/null || true
  rm -f "$SAIDA" "$LOG"
}
trap cleanup EXIT

for _ in $(seq 1 240); do
  if [ -s "$SAIDA" ]; then break; fi
  if ! kill -0 "$SERVIDOR" 2>/dev/null; then
    echo "O servidor descartável caiu ao subir:" >&2
    cat "$LOG" >&2
    exit 1
  fi
  sleep 0.25
done
[ -s "$SAIDA" ] || { echo "O servidor descartável não subiu a tempo." >&2; cat "$LOG" >&2; exit 1; }

# shellcheck disable=SC1090
source "$SAIDA"
cd "$AQUI/packages/corrida_core"
CORRIDA_URL="$URL" CORRIDA_ADMIN_PHONE="$ADMIN_PHONE" dart test test_contract "$@"
