"""O relatório da rodada, em português, e a lista de problemas que decide se ela passou."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from simulator.model import Outcome
from simulator.stats import RideRecord, percentile

OUTCOMES = {
    "completed": "concluídas",
    "cancelled": "canceladas pelo passageiro",
    "no_rider": "sem moto (ninguém aceitou)",
    "pix_expired": "Pix venceu e o servidor cancelou",
    "arrival_wait": "o passageiro não apareceu e o servidor cancelou",
    "unknown": "sem desfecho claro",
    "open": "ainda abertas no fim",
}


@dataclass(frozen=True)
class Report:
    text: str
    problems: list[str]

    @property
    def passed(self) -> bool:
        return not self.problems


def brl(cents: float) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


def span(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


def _gaps(rides: list[RideRecord], start: str, end: str) -> list[float]:
    return [
        getattr(r, end) - getattr(r, start) for r in rides if getattr(r, start) is not None and getattr(r, end) is not None
    ]


def _spread(values: list[float]) -> str:
    return f"mediana {span(percentile(values, 0.5))}, 90% até {span(percentile(values, 0.9))} ({len(values)} corridas)" if values else "sem dados"


def find_problems(outcome: Outcome, server_problems: list[str]) -> list[str]:
    stats, audit = outcome.stats, outcome.audit
    problems: list[str] = []
    if stats.unexpected_total:
        problems.append(f"O servidor deu {stats.unexpected_total} resposta(s) inesperada(s) (veja a lista abaixo).")
    if not audit:
        problems.append("Não consegui pedir a conferência final ao servidor.")
    else:
        if not audit.get("ledger_balanced", False):
            problems.append("O livro-caixa NÃO fecha (alguma cobrança não soma zero).")
        if audit.get("reconcile_diff"):
            problems.append(f"O livro-caixa não bate com o extrato do provedor: {audit['reconcile_diff']}")
        if audit.get("double_booked_riders"):
            problems.append(f"Motoqueiro com duas corridas ativas ao mesmo tempo: {audit['double_booked_riders']}")
        mine = [r for r in audit.get("open_rides", []) if r["ride_id"] in stats.rides]
        if mine:
            problems.append(f"{len(mine)} corrida(s) ficaram abertas depois da espera final: {[r['state'] for r in mine]}")
    unknown = [r.ride_id for r in stats.rides.values() if r.outcome == "unknown"]
    if unknown:
        problems.append(f"{len(unknown)} corrida(s) sumiram do estado sem nenhum aviso final.")
    missing = sum(len(r.missing_events) for r in stats.rides.values())
    if missing:
        problems.append(f"{missing} aviso(s) em tempo real esperado(s) não chegaram, sem a conexão ter caído.")
    problems += [f"No registro do servidor: {line}" for line in server_problems[:5]]
    return problems


def build_report(outcome: Outcome, server_problems: list[str] | None = None, retries: int = 0) -> Report:
    cfg, stats, audit = outcome.config, outcome.stats, outcome.audit
    server_problems = server_problems or []
    rides = list(stats.rides.values())
    by_outcome = Counter(r.outcome or "open" for r in rides)
    done = [r for r in rides if r.outcome == "completed"]
    lines = [
        "# Relatório da simulação", "",
        f"- Duração: {span(outcome.seconds)} · perfil {cfg.profile.name} · semente {cfg.seed}",
        f"- Gente: {cfg.riders} motoqueiros (no máximo {outcome.riders_online_peak} disponíveis ao mesmo tempo) e "
        f"{cfg.passengers} passageiros", "",
        "## Corridas", "",
        f"Pedidas: **{len(rides)}**",
    ]
    lines += [f"- {OUTCOMES.get(key, key)}: {count}" for key, count in by_outcome.most_common()]
    lines += [
        "", "## Tempos", "",
        f"- Da procura até alguém aceitar: {_spread(_gaps(rides, 'requested_at', 'accepted_at'))}",
        f"- Do aceite até a moto chegar: {_spread(_gaps(rides, 'accepted_at', 'arrived_at'))}",
        f"- Da saída até o fim da corrida: {_spread(_gaps(done, 'started_at', 'ended_at'))}", "",
        "## Dinheiro", "",
    ]
    for method, name in (("pix", "Pix"), ("cash", "dinheiro")):
        mine = [r for r in done if r.method == method]
        lines.append(f"- {name}: {len(mine)} corridas, {brl(sum(r.price_cents for r in mine))}")
    if stats.price_reasons:
        lines.append("- Preços mostrados: " + ", ".join(f"{k} ({v})" for k, v in stats.price_reasons.most_common()))
    lines += ["", "## O que as pessoas fizeram", ""]
    lines += [f"- {key}: {count}" for key, count in sorted(stats.notes.items())] or ["- nada de especial"]
    lines += ["", "## Avisos em tempo real recebidos (de todos, somados)", ""]
    lines += [f"- {key}: {count}" for key, count in sorted(stats.events.items())] or ["- nenhum"]
    if stats.closes:
        lines.append("- Conexões encerradas: " + ", ".join(f"{k} ({v})" for k, v in sorted(stats.closes.items())))
    if stats.events["mock_location_suspected"]:
        lines.append(
            f"- Suspeitas de localização falsa que o servidor avisou ao administrador: {stats.events['mock_location_suspected']} "
            "(o simulador não falsifica nada; costuma ser moto rápida demais para o intervalo entre as posições)"
        )
    lines += ["", "## Chamadas à API", "", "| Rota | Chamadas | Erros | Mediana | 90% | Máximo |", "|---|---:|---:|---:|---:|---:|"]
    totals: Counter = Counter()
    errors: Counter = Counter()
    for (method, template, status), count in stats.calls.items():
        totals[(method, template)] += count
        if status == 0 or status >= 400:
            errors[(method, template)] += count
    for key, count in totals.most_common():
        times = stats.latency[key]
        ms = lambda q: f"{(percentile(times, q) or 0) * 1000:.0f} ms"  # noqa: E731
        lines.append(f"| {key[0]} {key[1]} | {count} | {errors[key]} | {ms(0.5)} | {ms(0.9)} | {ms(1.0)} |")
    lines.append(f"\nTotal: {sum(totals.values())} chamadas.")
    if retries:
        lines.append(f"O servidor repetiu {retries} operação(ões) por impasse no banco (esperado com muita gente ao mesmo tempo).")
    lines += ["", "## Respostas inesperadas do servidor", ""]
    lines += [f"- {text}" for text in stats.unexpected] or ["- nenhuma"]
    if stats.unexpected_total > len(stats.unexpected):
        lines.append(f"- … e mais {stats.unexpected_total - len(stats.unexpected)}")
    lines += ["", "## Conferência final do servidor", ""]
    if audit:
        lines += [
            f"- Livro-caixa fecha: {'sim' if audit.get('ledger_balanced') else 'NÃO'}",
            f"- Bate com o extrato do provedor: {'sim' if not audit.get('reconcile_diff') else 'NÃO'}",
            f"- Corridas por estado no banco: {audit.get('rides_by_state')}",
        ]
    else:
        lines.append("- sem resposta")
    problems = find_problems(outcome, server_problems)
    lines += ["", "## Veredito", ""]
    lines += ["**Tudo certo.**"] if not problems else ["**Problemas encontrados:**"] + [f"{i}. {p}" for i, p in enumerate(problems, 1)]
    return Report("\n".join(lines) + "\n", problems)
