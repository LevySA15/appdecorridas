"""Sobe o servidor descartável do simulador e fica no ar até receber SIGTERM/SIGINT.

Serve ao teste de contrato dos apps (`mobile/tool/contrato.sh`): escreve `URL=...` e `ADMIN_PHONE=...` no arquivo de
`--out` quando o servidor está pronto, e apaga tudo (esquema, Redis, fotos) ao sair.

    cd server && .venv/bin/python scripts/sandbox_server.py --out /tmp/sandbox.env
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulator.sandbox import ADMIN_PHONE, Sandbox  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="arquivo onde escrever URL e ADMIN_PHONE quando estiver pronto")
    parser.add_argument("--redis-db", type=int, default=12, help="banco do Redis (esvaziado no fim)")
    args = parser.parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with Sandbox(fast=True, redis_db=args.redis_db) as box:
        out = Path(args.out)
        out.write_text(f"URL={box.url}\nADMIN_PHONE='{ADMIN_PHONE}'\n", encoding="utf-8")
        stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
