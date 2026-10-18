"""Linha de comando do simulador. Uso (a partir de `server/`):

    .venv/bin/python -m simulator demo                     # sobe um servidor descartável, simula e apaga tudo
    .venv/bin/python -m simulator run --url http://127.0.0.1:8000 --admin-phone "75 99999-0000"
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import sys
from pathlib import Path

from simulator.behavior import fast_timings, preset
from simulator.report import build_report
from simulator.model import SimConfig
from simulator.runner import simulate
from simulator.sandbox import ADMIN_PHONE, SERVER_DIR, Sandbox
from simulator.world import SimulationError

DEFAULT_OUT = SERVER_DIR / "var" / "sim"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simulator", description="Motoqueiros e passageiros de mentira em Santo Antônio de Jesus.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("demo", "sobe um servidor descartável (prazos curtos com --fast), simula e apaga tudo"),
        ("run", "simula contra um servidor que já está no ar (modo de desenvolvimento)"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--riders", type=int, default=8)
        cmd.add_argument("--passengers", type=int, default=16)
        cmd.add_argument("--minutes", type=float, default=10.0)
        cmd.add_argument("--seed", type=int, default=1)
        cmd.add_argument("--profile", default="normal", help="calmo, normal ou bagunca")
        cmd.add_argument("--speed", type=float, default=1.0, help="multiplica a velocidade das motos (até 4)")
        cmd.add_argument("--pace", type=float, default=1.0, help="multiplica as esperas das pessoas (0.2 = cinco vezes mais depressa)")
        cmd.add_argument("--max-rides", type=int, default=None, help="para depois de tantos pedidos")
        cmd.add_argument("--city-scale", type=float, default=1.0, help="encolhe a cidade (0.2 = viagens bem curtas)")
        cmd.add_argument("--out", type=Path, default=DEFAULT_OUT, help="pasta do relatório")
    sub.choices["demo"].add_argument("--fast", action="store_true", help="prazos curtos no servidor e gente mais rápida")
    sub.choices["run"].add_argument("--url", default="http://127.0.0.1:8000")
    sub.choices["run"].add_argument("--admin-phone", required=True, help="o administrador criado com app.cli create-admin")
    return parser


def make_config(args: argparse.Namespace, url: str, admin_phone: str, *, fast: bool) -> SimConfig:
    profile = dataclasses.replace(
        preset(args.profile), speedup=args.speed, pace=args.pace, city_scale=args.city_scale
    )
    if fast:
        profile = fast_timings(profile)
    return SimConfig(
        url=url, admin_phone=admin_phone, riders=args.riders, passengers=args.passengers, minutes=args.minutes,
        seed=args.seed, profile=profile, max_rides=args.max_rides, state_dir=args.out, on_status=print,
    )


def write_report(text: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"relatorio-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "demo":
            with Sandbox(fast=args.fast) as box:
                config = make_config(args, box.url, ADMIN_PHONE, fast=args.fast)
                config.state_dir = None            # servidor novo, ninguém para reencontrar
                outcome = asyncio.run(simulate(config))
                report = build_report(outcome, box.problems(), box.retries())
        else:
            outcome = asyncio.run(simulate(make_config(args, args.url, args.admin_phone, fast=False)))
            report = build_report(outcome)
    except (SimulationError, ValueError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrompido. O servidor descartável foi apagado.", file=sys.stderr)
        return 130
    print("\n" + report.text)
    print(f"Relatório gravado em {write_report(report.text, args.out)}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
